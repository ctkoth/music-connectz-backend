import AuthenticationServices
import Foundation
import SwiftUI

/// The one source of truth for "who is signed in".
///
/// Views observe this; nothing else reads the Keychain directly. That keeps
/// sign-out to a single place — if a view could clear tokens on its own, some
/// screen would eventually forget to reset the rest of the state.
@MainActor
final class Session: ObservableObject {
    enum State: Equatable {
        case loading
        case signedOut
        case signedIn(User)
    }

    @Published private(set) var state: State = .loading
    @Published var errorMessage: String?
    /// Fetched once and shared with TourView so launch costs one request, not two.
    @Published private(set) var tour: TourPayload?

    var user: User? {
        if case .signedIn(let user) = state { return user }
        return nil
    }

    /// A member who hasn't finished or skipped the tour gets OmviardZ on launch
    /// rather than an empty feed — same as the Android app. While the tour
    /// payload is still loading we do NOT show it: flashing the tour at someone
    /// who finished it months ago is worse than a beat of delay.
    var needsTour: Bool {
        guard let tour else { return false }
        return !(tour.progress?.isFinished ?? false)
    }

    func loadTour() async {
        tour = try? await APIClient.shared.get("api/omviardz/tour/", as: TourPayload.self)
    }

    /// Called when the tour ends so routing updates without a round trip.
    func markTourFinished() {
        guard let tour else { return }
        self.tour = TourPayload(steps: tour.steps, resume: tour.resume,
                                progress: TourProgress(skipped: true, completed: true))
    }

    // MARK: - Lifecycle

    func restore() async {
        guard TokenStore.isSignedIn else {
            state = .signedOut
            return
        }
        do {
            let user = try await APIClient.shared.get("api/auth/me/", as: User.self)
            state = .signedIn(user)
            await loadTour()
        } catch {
            // A stored token that no longer works is not an error worth showing
            // on launch — it's just an expired session.
            TokenStore.clear()
            state = .signedOut
        }
    }

    func signIn(identifier: String, password: String) async {
        await authenticate {
            try await APIClient.shared.post("api/auth/login/",
                                            body: LoginRequest(identifier: identifier,
                                                               password: password),
                                            as: AuthResponse.self)
        }
    }

    func register(username: String, email: String, password: String) async {
        await authenticate {
            try await APIClient.shared.post("api/auth/register/",
                                            body: RegisterRequest(username: username,
                                                                  email: email,
                                                                  password: password),
                                            as: AuthResponse.self)
        }
    }

    /// Native Sign in with Apple. The identity token goes to the backend, which
    /// verifies it against Apple's public keys — we never trust the client's
    /// word about who this is.
    func completeAppleSignIn(_ result: Result<ASAuthorization, Error>) async {
        switch result {
        case .failure(let error):
            // The user tapping Cancel is not a failure to report.
            if (error as? ASAuthorizationError)?.code == .canceled { return }
            errorMessage = "Apple sign-in didn't complete."
        case .success(let auth):
            guard let credential = auth.credential as? ASAuthorizationAppleIDCredential,
                  let data = credential.identityToken,
                  let token = String(data: data, encoding: .utf8) else {
                errorMessage = "Apple didn't return a usable identity token."
                return
            }
            await authenticate {
                try await APIClient.shared.post("api/auth/oauth/apple/",
                                                body: AppleSignInRequest(id_token: token),
                                                as: AuthResponse.self)
            }
        }
    }

    func signOut() {
        TokenStore.clear()
        state = .signedOut
    }

    func refreshUser() async {
        guard case .signedIn = state else { return }
        if let user = try? await APIClient.shared.get("api/auth/me/", as: User.self) {
            state = .signedIn(user)
        }
    }

    // MARK: - Private

    private func authenticate(_ call: () async throws -> AuthResponse) async {
        errorMessage = nil
        do {
            let response = try await call()
            TokenStore.access = response.access
            TokenStore.refresh = response.refresh
            state = .signedIn(response.user)
            await loadTour()
        } catch {
            errorMessage = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
    }
}
