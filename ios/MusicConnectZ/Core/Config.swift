import Foundation

/// Everything environment-specific, in one place.
///
/// The base URL is read from Info.plist (`MCZBaseURL`) so a TestFlight build and
/// a local build can point at different backends without touching code. It falls
/// back to production rather than to localhost — a build that silently talks to
/// 127.0.0.1 looks like it works right up until a reviewer opens it.
enum Config {
    static let baseURL: URL = {
        let fallback = URL(string: "https://musicconnectz.net")!
        guard let raw = Bundle.main.object(forInfoDictionaryKey: "MCZBaseURL") as? String,
              !raw.isEmpty,
              let url = URL(string: raw) else { return fallback }
        return url
    }()

    /// Sign in with Apple mints tokens whose audience is this bundle ID. The
    /// backend must list it in APPLE_OAUTH_BUNDLE_ID or every native sign-in is
    /// rejected with "Apple rejected that sign-in token."
    static var bundleID: String {
        Bundle.main.bundleIdentifier ?? "net.musicconnectz.app"
    }

    static var appVersion: String {
        let v = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
        let b = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String
        return "\(v ?? "0") (\(b ?? "0"))"
    }
}
