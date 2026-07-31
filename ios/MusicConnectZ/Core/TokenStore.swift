import Foundation
import Security

/// JWTs live in the Keychain, not UserDefaults.
///
/// UserDefaults is a plist in the app container — readable from a backup, and
/// from any process that gets at the device filesystem. A stolen refresh token
/// is a full account takeover that outlives a password change, so it gets the
/// Keychain and `ThisDeviceOnly` (excluded from iCloud/iTunes backups).
struct TokenStore {
    private static let service = "net.musicconnectz.app.tokens"
    private static let accessKey = "access"
    private static let refreshKey = "refresh"

    // No `nonmutating` on these setters: static members are already nonmutating,
    // and saying so is a compile error rather than a redundancy.
    static var access: String? {
        get { read(accessKey) }
        set { write(accessKey, newValue) }
    }

    static var refresh: String? {
        get { read(refreshKey) }
        set { write(refreshKey, newValue) }
    }

    static var isSignedIn: Bool { access?.isEmpty == false }

    static func clear() {
        write(accessKey, nil)
        write(refreshKey, nil)
    }

    // MARK: - Keychain

    private static func query(_ key: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: key]
    }

    private static func read(_ key: String) -> String? {
        var q = query(key)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func write(_ key: String, _ value: String?) {
        // Delete-then-add rather than SecItemUpdate: it's one code path for
        // create, replace and clear, and it can't leave a stale item behind.
        SecItemDelete(query(key) as CFDictionary)
        guard let value, let data = value.data(using: .utf8) else { return }
        var q = query(key)
        q[kSecValueData as String] = data
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(q as CFDictionary, nil)
    }
}
