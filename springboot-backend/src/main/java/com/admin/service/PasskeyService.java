package com.admin.service;

import com.admin.common.lang.R;
import com.admin.common.utils.JwtUtil;
import com.admin.common.utils.Md5Util;
import com.admin.entity.User;
import com.admin.mapper.UserMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yubico.webauthn.*;
import com.yubico.webauthn.data.*;
import jakarta.annotation.PostConstruct;
import org.springframework.boot.sql.init.dependency.DependsOnDatabaseInitialization;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.security.SecureRandom;
import java.util.*;
import java.util.stream.Collectors;

/**
 * WebAuthn ceremonies are server-generated, bounded, single-use and bound to
 * their purpose. The panel remains a single-instance application. Only public
 * credential material is stored; authenticator private keys never leave the device.
 */
@Service
@DependsOnDatabaseInitialization
public class PasskeyService implements CredentialRepository {
    private static final long TTL = 120_000;
    private static final int MAX_PENDING = 512;
    private static final int MAX_PUBLIC_PENDING = 384;
    private static final int MAX_KEYS = 20;
    private final JdbcTemplate jdbc;
    private final UserMapper users;
    private final ObjectMapper json;
    private final Environment env;
    private final SecureRandom random = new SecureRandom();
    private final Map<String, Pending> pending = new LinkedHashMap<>();
    private String origin;
    private String rpId;
    private RelyingParty rp;
    private boolean recovery;

    private record Pending(String purpose, Long userId, String token, Object options, long expires) {}
    private record Key(long id, long userId, String credentialId, String handle, String cose,
                       long count, String label, long created, long used, boolean eligible, boolean backedUp) {}

    public static final class Denied extends RuntimeException {
        public Denied(String message) { super(message); }
    }

    public PasskeyService(JdbcTemplate jdbc, UserMapper users, ObjectMapper json, Environment env) {
        this.jdbc = jdbc;
        this.users = users;
        this.json = json;
        this.env = env;
    }

    @PostConstruct
    void configure() {
        recovery = env.getProperty("PASSKEY_RECOVERY_PASSWORD_LOGIN", Boolean.class, false);
        if (env.getProperty("PASSKEY_ENABLED", Boolean.class, false)) {
            String configured = env.getProperty("PASSKEY_ORIGIN", "").trim();
            URI uri = URI.create(configured);
            String host = uri.getHost();
            if (host == null || uri.getUserInfo() != null || uri.getRawQuery() != null ||
                    uri.getRawFragment() != null || (uri.getRawPath() != null && !uri.getRawPath().isEmpty()) ||
                    !("https".equals(uri.getScheme()) || ("http".equals(uri.getScheme()) && "localhost".equals(host)))) {
                throw new IllegalArgumentException("PASSKEY_ORIGIN must be an exact HTTPS origin (or http://localhost), without a path");
            }
            rpId = host.toLowerCase(Locale.ROOT);
            int port = uri.getPort();
            if (port == 443 && "https".equals(uri.getScheme()) || port == 80 && "http".equals(uri.getScheme())) port = -1;
            origin = uri.getScheme() + "://" + rpId + (port < 0 ? "" : ":" + port);
            rp = RelyingParty.builder()
                    .identity(RelyingPartyIdentity.builder().id(rpId).name("Flux Panel").build())
                    .credentialRepository(this)
                    .origins(Set.of(origin))
                    .allowOriginPort(false).allowOriginSubdomain(false)
                    .attestationConveyancePreference(AttestationConveyancePreference.NONE)
                    .preferredPubkeyParams(List.of(PublicKeyCredentialParameters.ES256, PublicKeyCredentialParameters.RS256))
                    .validateSignatureCounter(true)
                    .build();
        }
        if (!passwordEnabled() && (rp == null || !allActiveUsersReady())) {
            throw new IllegalStateException("Passkey-only policy has no usable coverage for this RP. Set PASSKEY_RECOVERY_PASSWORD_LOGIN=true temporarily to recover.");
        }
    }

    public boolean enabled() { return rp != null; }

    public synchronized boolean passwordEnabled() {
        return recovery || storedPasswordEnabled();
    }

    private boolean storedPasswordEnabled() {
        List<Integer> values = jdbc.queryForList("SELECT password_enabled FROM passkey_policy WHERE id=1", Integer.class);
        return values.isEmpty() || values.getFirst() == 1;
    }

    public synchronized boolean hasVerifiedKey(long userId) {
        if (!enabled()) return false;
        return count("SELECT count(*) FROM passkey_credential WHERE user_id=? AND rp_id=? AND last_used_at>0", userId, rpId) > 0;
    }

    private long count(String sql, Object... args) {
        return Objects.requireNonNull(jdbc.queryForObject(sql, Long.class, args));
    }

    private boolean allActiveUsersReady() {
        if (!enabled()) return false;
        return count("SELECT count(*) FROM app_user WHERE status<>0 AND role_id=0") > 0
                && count("SELECT count(*) FROM app_user u WHERE u.status<>0 AND NOT EXISTS " +
                "(SELECT 1 FROM passkey_credential p WHERE p.user_id=u.id AND p.rp_id=? AND p.last_used_at>0)", rpId) == 0;
    }

    public synchronized R modes() {
        return R.ok(Map.of("passkeyEnabled", enabled(), "passwordEnabled", passwordEnabled(),
                "origin", enabled() ? origin : "", "recovery", recovery,
                "storedPasswordEnabled", storedPasswordEnabled()));
    }

    private void requireEnabled() {
        if (!enabled()) throw new Denied("Passkey 登录未启用");
    }

    private User activeUser(long id) {
        User user = users.selectById(id);
        if (user == null || user.getStatus() == null || user.getStatus() == 0)
            throw new Denied("账户不可用");
        return user;
    }

    private User session(String token) {
        if (!JwtUtil.validateToken(token)) throw new Denied("请重新登录");
        return activeUser(JwtUtil.getUserIdFromToken(token));
    }

    private String randomId() {
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private void prune() {
        long now = System.currentTimeMillis();
        pending.values().removeIf(p -> p.expires() <= now);
    }

    private String remember(String purpose, Long userId, String token, Object options) {
        prune();
        // One outstanding ceremony of each authenticated purpose per session.
        if (token != null) pending.values().removeIf(p -> purpose.equals(p.purpose()) && token.equals(p.token()));
        // Anonymous requests cannot consume the capacity reserved for signed-in
        // credential management. Evict the oldest anonymous request if needed.
        if (token == null && pending.values().stream().filter(p -> p.token() == null).count() >= MAX_PUBLIC_PENDING) {
            var iterator = pending.values().iterator();
            while (iterator.hasNext()) {
                if (iterator.next().token() == null) { iterator.remove(); break; }
            }
        }
        if (pending.size() >= MAX_PENDING) throw new Denied("验证请求过多，请稍后重试");
        String id = randomId();
        pending.put(id, new Pending(purpose, userId, token, options, System.currentTimeMillis() + TTL));
        return id;
    }

    private Pending consume(String id, String purpose, Long userId, String token) {
        prune();
        Pending p = pending.get(id);
        if (p == null || !purpose.equals(p.purpose()) || !Objects.equals(userId, p.userId()) ||
                !Objects.equals(token, p.token())) throw new Denied("验证请求已失效，请重试");
        pending.remove(id);
        return p;
    }

    private JsonNode credential(JsonNode body) throws Exception {
        JsonNode c = body.path("credential");
        if (!c.isObject() || c.toString().length() > 65536) throw new Denied("无效的 Passkey 响应");
        byte[] raw = Base64.getUrlDecoder().decode(c.path("response").path("clientDataJSON").asText());
        JsonNode client = json.readTree(raw);
        if (client == null || !client.isObject() || client.path("crossOrigin").asBoolean(false) || client.has("topOrigin"))
            throw new Denied("不允许跨站嵌入的 Passkey 验证");
        return c;
    }

    private void authorize(User user, String token, JsonNode body) {
        String proof = body.path("proof").asText("");
        if (!proof.isEmpty()) {
            consume(proof, "proof", user.getId(), token);
            return;
        }
        if (!passwordEnabled() || !Objects.equals(user.getPwd(), Md5Util.md5(body.path("password").asText(""))))
            throw new Denied("请使用当前密码或 Passkey 重新验证身份");
    }

    private List<Key> keys(String where, Object... args) {
        return jdbc.query("SELECT id,user_id,credential_id,user_handle,public_key_cose,signature_count,label,created_at,last_used_at,backup_eligible,backed_up " +
                        "FROM passkey_credential WHERE " + where,
                (rs, n) -> new Key(rs.getLong(1), rs.getLong(2), rs.getString(3), rs.getString(4), rs.getString(5),
                        rs.getLong(6), rs.getString(7), rs.getLong(8), rs.getLong(9), rs.getInt(10) == 1, rs.getInt(11) == 1), args);
    }

    private static ByteArray bytes(String base64) {
        return new ByteArray(Base64.getUrlDecoder().decode(base64));
    }

    private List<Key> userKeys(long uid) { return keys("user_id=? AND rp_id=? ORDER BY id", uid, rpId); }

    private Optional<Long> usernameId(String username) {
        return jdbc.queryForList("SELECT id FROM app_user WHERE username=? AND status<>0", Long.class, username).stream().findFirst();
    }

    @Override
    public Set<PublicKeyCredentialDescriptor> getCredentialIdsForUsername(String username) {
        return usernameId(username).map(this::userKeys).orElse(List.of()).stream()
                .map(k -> PublicKeyCredentialDescriptor.builder().id(bytes(k.credentialId())).build())
                .collect(Collectors.toSet());
    }

    @Override
    public Optional<ByteArray> getUserHandleForUsername(String username) {
        return usernameId(username).flatMap(uid -> userKeys(uid).stream().findFirst()).map(k -> bytes(k.handle()));
    }

    @Override
    public Optional<String> getUsernameForUserHandle(ByteArray handle) {
        return jdbc.queryForList("SELECT DISTINCT u.username FROM app_user u JOIN passkey_credential p ON p.user_id=u.id " +
                "WHERE p.rp_id=? AND p.user_handle=? AND u.status<>0", String.class, rpId, handle.getBase64Url()).stream().findFirst();
    }

    private RegisteredCredential registered(Key k) {
        return RegisteredCredential.builder().credentialId(bytes(k.credentialId())).userHandle(bytes(k.handle()))
                .publicKeyCose(bytes(k.cose())).signatureCount(k.count())
                .backupEligible(k.eligible()).backupState(k.backedUp()).build();
    }

    @Override
    public Optional<RegisteredCredential> lookup(ByteArray id, ByteArray handle) {
        return keys("rp_id=? AND credential_id=? AND user_handle=?", rpId, id.getBase64Url(), handle.getBase64Url())
                .stream().findFirst().map(this::registered);
    }

    @Override
    public Set<RegisteredCredential> lookupAll(ByteArray id) {
        return keys("rp_id=? AND credential_id=?", rpId, id.getBase64Url()).stream().map(this::registered).collect(Collectors.toSet());
    }

    public synchronized R list(String token) {
        User user = session(token);
        List<Map<String,Object>> result = enabled() ? userKeys(user.getId()).stream()
                .map(k -> Map.<String,Object>of("id", k.id(), "label", k.label(), "createdAt", k.created(),
                        "lastUsedAt", k.used(), "backedUp", k.backedUp())).toList() : List.of();
        return R.ok(Map.of("passkeyEnabled", enabled(), "passwordEnabled", passwordEnabled(),
                "recovery", recovery, "storedPasswordEnabled", storedPasswordEnabled(),
                "origin", enabled() ? origin : "", "admin", user.getRoleId() == 0, "keys", result,
                "allUsersReady", enabled() && user.getRoleId() == 0 && allActiveUsersReady()));
    }

    public synchronized R registerOptions(String token, JsonNode body) throws Exception {
        requireEnabled();
        User user = session(token);
        // Do not allow the initial factory password to establish persistent credentials.
        if ("admin_user".equalsIgnoreCase(user.getUser()) || Objects.equals(user.getPwd(), Md5Util.md5("admin_user")))
            throw new Denied("请先修改默认账号及密码");
        authorize(user, token, body);
        List<Key> existing = userKeys(user.getId());
        if (existing.size() >= MAX_KEYS) throw new Denied("Passkey 数量已达上限");
        ByteArray handle = existing.isEmpty() ? bytes(randomId()) : bytes(existing.getFirst().handle());
        PublicKeyCredentialCreationOptions options = rp.startRegistration(StartRegistrationOptions.builder()
                .user(UserIdentity.builder().name(user.getUser()).displayName(user.getUser()).id(handle).build())
                .authenticatorSelection(AuthenticatorSelectionCriteria.builder()
                        .residentKey(ResidentKeyRequirement.REQUIRED)
                        .userVerification(UserVerificationRequirement.REQUIRED).build())
                .timeout(TTL).build());
        String id = remember("register", user.getId(), token, options);
        return R.ok(Map.of("requestId", id, "options", json.readTree(options.toCredentialsCreateJson()).path("publicKey")));
    }

    public synchronized R registerFinish(String token, JsonNode body) throws Exception {
        requireEnabled();
        User user = session(token);
        Pending p = consume(body.path("requestId").asText(), "register", user.getId(), token);
        var options = (PublicKeyCredentialCreationOptions) p.options();
        List<Key> existing = userKeys(user.getId());
        if (!options.getUser().getName().equals(user.getUser()) || existing.size() >= MAX_KEYS ||
                (!existing.isEmpty() && !existing.getFirst().handle().equals(options.getUser().getId().getBase64Url())))
            throw new Denied("账号或凭证状态已变化，请重新注册");
        String label = body.path("label").asText("Passkey").strip();
        if (label.isEmpty() || label.length() > 100) throw new Denied("Passkey 名称须为 1 至 100 个字符");
        var response = PublicKeyCredential.parseRegistrationResponseJson(credential(body).toString());
        RegistrationResult result = rp.finishRegistration(FinishRegistrationOptions.builder().request(options).response(response).build());
        if (!result.isUserVerified() || result.isDiscoverable().orElse(true) == false)
            throw new Denied("需要支持用户验证和可发现凭证的 Passkey");
        if (count("SELECT count(*) FROM passkey_credential WHERE rp_id=? AND credential_id=?", rpId, result.getKeyId().getId().getBase64Url()) != 0)
            throw new Denied("该 Passkey 已注册");
        jdbc.update("INSERT INTO passkey_credential(user_id,rp_id,credential_id,user_handle,public_key_cose,signature_count,label,created_at,last_used_at,backup_eligible,backed_up) " +
                        "VALUES(?,?,?,?,?,?,?,?,0,?,?)", user.getId(), rpId, result.getKeyId().getId().getBase64Url(),
                options.getUser().getId().getBase64Url(), result.getPublicKeyCose().getBase64Url(), result.getSignatureCount(),
                label, System.currentTimeMillis(), result.isBackupEligible() ? 1 : 0, result.isBackedUp() ? 1 : 0);
        return R.ok();
    }

    public synchronized R assertionOptions(String token, boolean reauth) throws Exception {
        requireEnabled();
        User user = reauth ? session(token) : null;
        var builder = StartAssertionOptions.builder().userVerification(UserVerificationRequirement.REQUIRED).timeout(TTL);
        if (reauth && userKeys(user.getId()).isEmpty()) throw new Denied("尚未绑定 Passkey");
        // Both flows are discoverable assertions. A credential marked verified
        // must actually work without a username or allowCredentials list.
        // Reauthentication additionally checks the authenticated user ID below.
        AssertionRequest options = rp.startAssertion(builder.build());
        String id = remember(reauth ? "reauth" : "login", reauth ? user.getId() : null, reauth ? token : null, options);
        return R.ok(Map.of("requestId", id, "options", json.readTree(options.toCredentialsGetJson()).path("publicKey")));
    }

    public synchronized R assertionFinish(String token, boolean reauth, JsonNode body) throws Exception {
        requireEnabled();
        User current = reauth ? session(token) : null;
        Pending p = consume(body.path("requestId").asText(), reauth ? "reauth" : "login",
                reauth ? current.getId() : null, reauth ? token : null);
        var response = PublicKeyCredential.parseAssertionResponseJson(credential(body).toString());
        AssertionResult result = rp.finishAssertion(FinishAssertionOptions.builder()
                .request((AssertionRequest) p.options()).response(response).build());
        if (!result.isSuccess() || !result.isUserVerified()) throw new Denied("Passkey 验证失败");
        var registered = result.getCredential();
        Key key = keys("rp_id=? AND credential_id=? AND user_handle=?", rpId, registered.getCredentialId().getBase64Url(),
                registered.getUserHandle().getBase64Url()).stream().findFirst().orElseThrow(() -> new Denied("Passkey 不可用"));
        User user = activeUser(key.userId());
        if (!result.getUsername().equals(user.getUser()) || (reauth && !current.getId().equals(user.getId())))
            throw new Denied("Passkey 与当前用户不匹配");
        if (jdbc.update("UPDATE passkey_credential SET signature_count=?,last_used_at=?,backed_up=? WHERE id=? AND signature_count=?",
                result.getSignatureCount(), System.currentTimeMillis(), result.isBackedUp() ? 1 : 0, key.id(), key.count()) != 1)
            throw new Denied("凭证状态已变化，请重试");
        if (reauth) return R.ok(Map.of("proof", remember("proof", user.getId(), token, null)));
        return R.ok(Map.of("token", JwtUtil.generateToken(user), "name", user.getUser(),
                "role_id", user.getRoleId(), "requirePasswordChange", false));
    }

    public synchronized R delete(String token, JsonNode body) {
        requireEnabled();
        User user = session(token);
        authorize(user, token, body);
        long id = body.path("id").asLong(-1);
        List<Key> existing = userKeys(user.getId());
        if (existing.stream().noneMatch(k -> k.id() == id)) throw new Denied("Passkey 不存在");
        if (!passwordEnabled() && existing.stream().noneMatch(k -> k.id() != id && k.used() > 0))
            throw new Denied("仅 Passkey 登录时不能删除最后一个已验证的凭证");
        jdbc.update("DELETE FROM passkey_credential WHERE id=? AND user_id=? AND rp_id=?", id, user.getId(), rpId);
        return R.ok();
    }

    public synchronized R policy(String token, JsonNode body) {
        if (!enabled() && !recovery) requireEnabled();
        User user = session(token);
        if (user.getRoleId() != 0) throw new Denied("仅管理员可修改登录方式");
        if (!body.path("passwordEnabled").isBoolean()) throw new Denied("无效的登录配置");
        boolean enabled = body.path("passwordEnabled").asBoolean();
        // The explicit server-side recovery switch allows a fresh password
        // proof to permanently restore mixed mode, even if every key was lost.
        if (recovery && enabled) authorize(user, token, body);
        else consume(body.path("proof").asText(), "proof", user.getId(), token);
        if (!enabled && (recovery || !allActiveUsersReady()))
            throw new Denied("关闭前所有启用账号均须成功验证 Passkey，且必须退出应急恢复模式");
        jdbc.update("INSERT INTO passkey_policy(id,password_enabled) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET password_enabled=excluded.password_enabled",
                enabled ? 1 : 0);
        pending.clear();
        return R.ok();
    }
}
