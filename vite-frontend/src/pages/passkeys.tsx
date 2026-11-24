import {useEffect, useState} from 'react';
import {Button} from '@heroui/button';
import {Input} from '@heroui/input';
import {Card, CardBody} from '@heroui/card';
import toast from 'react-hot-toast';
import {listKeys, registerKey, deleteKey, reauth, setPasswordEnabled, supported, KeyList} from '@/utils/passkey';

export default function PasskeysPage() {
  const [state, setState] = useState<KeyList>();
  const [label, setLabel] = useState('My Passkey');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const refresh = async () => setState(await listKeys());
  useEffect(() => { refresh().catch(e => toast.error(e.message)); }, []);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try { await fn(); await refresh(); toast.success('操作成功'); }
    catch (e) { toast.error(e instanceof Error ? e.message : '操作失败'); }
    finally { setBusy(false); setPassword(''); }
  };
  const authorization = async () => password && state?.passwordEnabled ? {password} : {proof: await reauth()};
  if (!state) return <div className="p-6"><p>正在读取安全设置...</p><Button variant="light" onPress={() => refresh().catch(e => toast.error(e.message))}>重新加载</Button></div>;
  const browserReady = supported(state.origin);
  return <div className="p-4 space-y-4 max-w-3xl mx-auto">
    <h1 className="text-xl font-bold">Passkey 与登录安全</h1>
    {!state.passkeyEnabled ? <p>服务器尚未启用 Passkey，请配置 PASSKEY_ENABLED 和 PASSKEY_ORIGIN。</p> :
      <Card><CardBody className="space-y-4">
        {!browserReady && <p>当前环境不支持 Passkey 或访问地址与服务器配置不同，请使用 {state.origin} 登录。</p>}
        <p>新增或删除凭证需要重新验证。已绑定凭证时可直接使用 Passkey，首次绑定请输入当前密码。</p>
        {state.passwordEnabled && <Input label="当前密码（可选）" type="password" value={password} onValueChange={setPassword}/>}
        <Input label="凭证名称" value={label} onValueChange={setLabel} maxLength={100}/>
        <Button color="primary" isDisabled={busy || !browserReady} onPress={() => run(async () => registerKey(label, await authorization()))}>添加 Passkey</Button>
        {state.keys.map(k => <div key={k.id} className="border rounded-lg p-3 flex flex-wrap items-center justify-between gap-2">
          <div><b>{k.label}</b><p className="text-small text-default-500">{k.lastUsedAt ? '最近验证：' + new Date(k.lastUsedAt).toLocaleString() : '尚未验证'} · {k.backedUp ? '已同步备份' : '未同步备份'}</p></div>
          <Button color="danger" variant="light" isDisabled={busy} onPress={() => { if (confirm('确认删除此 Passkey？')) run(async () => deleteKey(k.id, await authorization())); }}>删除</Button>
        </div>)}
        {!!state.keys.length && <Button variant="bordered" isDisabled={busy || !browserReady} onPress={() => run(reauth)}>验证已绑定的 Passkey</Button>}
      </CardBody></Card>}
    {state.admin && (state.passkeyEnabled || state.recovery) && <Card><CardBody className="space-y-3">
      <h2 className="font-semibold">全局登录策略</h2>
      <p>账密登录：{state.passwordEnabled ? '已开启' : '已关闭'}</p>
      {state.recovery && <><p>服务器处于应急恢复模式。原策略：{state.storedPasswordEnabled ? '允许账密' : '仅 Passkey'}。</p>
        {!state.storedPasswordEnabled && <>
          <Input label="恢复策略所需的管理员当前密码" type="password" value={password} onValueChange={setPassword}/>
          <Button isDisabled={busy || !password} color="primary" onPress={() => run(() => setPasswordEnabled(true, {password}))}>永久恢复账密登录</Button>
        </>}
        <p>恢复后请移除服务器的应急环境变量。</p></>}
      {state.passwordEnabled && !state.allUsersReady && <p>所有启用账号均须完成 Passkey 验证后，才能关闭账密登录。</p>}
      {!state.recovery && <Button color={state.passwordEnabled ? 'danger' : 'primary'} isDisabled={busy || !browserReady || (state.passwordEnabled && (!state.allUsersReady || state.recovery))} onPress={() => {
        if (confirm(state.passwordEnabled ? '确定关闭所有用户的账密登录？' : '确定恢复账密登录？')) run(async () => setPasswordEnabled(!state.passwordEnabled, {proof: await reauth()}));
      }}>{state.passwordEnabled ? '关闭账密登录' : '恢复账密登录'}</Button>}
    </CardBody></Card>}
  </div>;
}
