import Network from '@/api/network';
import type { LoginResponse } from '@/api';

export interface Modes { passkeyEnabled: boolean; passwordEnabled: boolean; origin: string; recovery: boolean; storedPasswordEnabled: boolean; legacyBackend?: boolean }
export interface KeyInfo { id: number; label: string; createdAt: number; lastUsedAt: number; backedUp: boolean }
export interface KeyList extends Modes { admin: boolean; allUsersReady: boolean; keys: KeyInfo[] }
async function post<T>(path: string, data: object = {}): Promise<T> {
  const r = await Network.post<T>('/passkey/' + path, data, {anonymous: path.startsWith('login/')});
  if (r.code !== 0) throw new Error(r.msg);
  return r.data;
}
export async function modes(): Promise<Modes> {
  const r = await Network.post<Modes>('/passkey/modes', {}, {anonymous: true});
  if (r.code === 0 && r.data && typeof r.data.passwordEnabled === 'boolean' && typeof r.data.passkeyEnabled === 'boolean') return r.data;
  // The frontend and native backend images may update at different times.
  // A legacy backend has no public modes route and returns 401 or 404
  // (or Spring's missing static resource error). The backend still controls
  // whether the legacy login endpoint actually accepts passwords.
  if (r.code === 401 || r.code === 404 || (r.code === -2 && /No static resource .*passkey\/modes/i.test(r.msg))) {
    return {passkeyEnabled: false, passwordEnabled: true, storedPasswordEnabled: true, origin: '', recovery: false, legacyBackend: true};
  }
  throw new Error(r.msg || '无法读取登录方式');
}
export const listKeys = () => post<KeyList>('list');
export const supported = (origin?: string) => window.isSecureContext && !!window.PublicKeyCredential && !!navigator.credentials && (!origin || window.location.origin === origin);
const decode = (s: string) => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(s.length / 4) * 4, '=')), c => c.charCodeAt(0));
const encode = (b: ArrayBuffer) => btoa(Array.from(new Uint8Array(b), c => String.fromCharCode(c)).join('')).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
interface Ceremony { requestId: string; options: any }
function descriptors(items: any[]) { return items?.map(item => ({...item, id: decode(item.id)})); }
function serialize(c: PublicKeyCredential) {
  const r = c.response;
  const response = 'attestationObject' in r
    ? {clientDataJSON: encode(r.clientDataJSON), attestationObject: encode((r as AuthenticatorAttestationResponse).attestationObject), transports: (r as AuthenticatorAttestationResponse).getTransports?.() ?? []}
    : {clientDataJSON: encode(r.clientDataJSON), authenticatorData: encode((r as AuthenticatorAssertionResponse).authenticatorData),
       signature: encode((r as AuthenticatorAssertionResponse).signature),
       userHandle: (r as AuthenticatorAssertionResponse).userHandle ? encode((r as AuthenticatorAssertionResponse).userHandle!) : null};
  return {id: c.id, rawId: encode(c.rawId), type: c.type, response, clientExtensionResults: c.getClientExtensionResults()};
}
async function assertion<T>(purpose: 'login' | 'reauth') {
  if (!supported()) throw new Error('当前浏览器不支持 Passkey，请使用 HTTPS 浏览器');
  const {requestId, options} = await post<Ceremony>(purpose + '/options');
  const credential = await navigator.credentials.get({publicKey: {...options, challenge: decode(options.challenge), allowCredentials: descriptors(options.allowCredentials)}}) as PublicKeyCredential | null;
  if (!credential) throw new Error('验证已取消');
  return post<T>(purpose + '/finish', {requestId, credential: serialize(credential)});
}
export const passkeyLogin = () => assertion<LoginResponse>('login');
export const reauth = async () => (await assertion<{proof: string}>('reauth')).proof;
export async function registerKey(label: string, authorization: {password: string} | {proof: string}) {
  if (!supported()) throw new Error('当前浏览器不支持 Passkey，请使用 HTTPS 浏览器');
  const {requestId, options} = await post<Ceremony>('register/options', authorization);
  const credential = await navigator.credentials.create({publicKey: {...options, challenge: decode(options.challenge), user: {...options.user, id: decode(options.user.id)}, excludeCredentials: descriptors(options.excludeCredentials)}}) as PublicKeyCredential | null;
  if (!credential) throw new Error('注册已取消');
  await post('register/finish', {requestId, label, credential: serialize(credential)});
}
export const deleteKey = (id: number, authorization: {password: string} | {proof: string}) => post('delete', {id, ...authorization});
export const setPasswordEnabled = (passwordEnabled: boolean, authorization: {password: string} | {proof: string}) => post('policy', {passwordEnabled, ...authorization});
