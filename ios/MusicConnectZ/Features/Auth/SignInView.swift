import AuthenticationServices
import SwiftUI

struct SignInView: View {
    @EnvironmentObject private var session: Session
    @Environment(\.colorScheme) private var colorScheme

    @State private var mode: Mode = .signIn
    @State private var identifier = ""
    @State private var email = ""
    @State private var password = ""
    @State private var busy = false

    enum Mode { case signIn, register }

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                header

                VStack(spacing: 12) {
                    TextField(mode == .signIn ? "Username, email or phone" : "Username",
                              text: $identifier)
                        .textContentType(mode == .signIn ? .username : .nickname)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()

                    if mode == .register {
                        TextField("Email", text: $email)
                            .textContentType(.emailAddress)
                            .keyboardType(.emailAddress)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }

                    SecureField("Password", text: $password)
                        .textContentType(mode == .signIn ? .password : .newPassword)
                }
                .textFieldStyle(.roundedBorder)

                if let message = session.errorMessage {
                    Text(message)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                Button(action: submit) {
                    if busy {
                        ProgressView().frame(maxWidth: .infinity)
                    } else {
                        Text(mode == .signIn ? "Sign in" : "Create account")
                            .frame(maxWidth: .infinity)
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(busy || !isValid)

                dividerRow

                // Required by App Review guideline 4.8 once any other social
                // login is offered — and it's the login most iOS members expect.
                SignInWithAppleButton(.signIn) { request in
                    request.requestedScopes = [.fullName, .email]
                } onCompletion: { result in
                    Task { await session.completeAppleSignIn(result) }
                }
                .signInWithAppleButtonStyle(colorScheme == .dark ? .white : .black)
                .frame(height: 50)

                Button(mode == .signIn ? "New here? Create an account"
                                       : "Already have an account? Sign in") {
                    withAnimation { mode = mode == .signIn ? .register : .signIn }
                    session.errorMessage = nil
                }
                .font(.footnote)
                .padding(.top, 4)
            }
            .padding(24)
        }
        .scrollDismissesKeyboard(.interactively)
    }

    private var header: some View {
        VStack(spacing: 8) {
            Text("Music ConnectZ")
                .font(.largeTitle.bold())
            Text("Find the people who make what you make.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(.top, 40)
    }

    private var dividerRow: some View {
        HStack {
            Rectangle().frame(height: 1).foregroundStyle(.quaternary)
            Text("or").font(.caption).foregroundStyle(.secondary)
            Rectangle().frame(height: 1).foregroundStyle(.quaternary)
        }
    }

    private var isValid: Bool {
        guard !identifier.trimmingCharacters(in: .whitespaces).isEmpty,
              password.count >= 8 else { return false }
        if mode == .register { return email.contains("@") }
        return true
    }

    private func submit() {
        busy = true
        Task {
            if mode == .signIn {
                await session.signIn(identifier: identifier, password: password)
            } else {
                await session.register(username: identifier, email: email, password: password)
            }
            busy = false
        }
    }
}
