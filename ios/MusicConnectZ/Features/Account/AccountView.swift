import SwiftUI

struct AccountView: View {
    @EnvironmentObject private var session: Session
    @State private var confirmingDelete = false
    @State private var deleteError: String?

    var body: some View {
        NavigationStack {
            List {
                if let user = session.user {
                    Section {
                        LabeledContent("Member", value: user.username)
                        LabeledContent("Tier", value: user.tier.capitalized)
                        LabeledContent("SpinaZ", value: "\(user.spinaz)")
                        if !user.email.isEmpty {
                            LabeledContent("Email", value: user.email)
                        }
                    }

                    if !user.personas.isEmpty {
                        Section("Your personas") {
                            ForEach(user.personas, id: \.self) { Text($0.capitalized) }
                        }
                    }
                }

                Section {
                    Button("Sign out", role: .destructive) { session.signOut() }
                }

                // Apple requires account deletion to be reachable from INSIDE the
                // app for anything that lets you create an account — a support
                // email or a website link is an explicit rejection.
                Section {
                    Button("Delete my account", role: .destructive) {
                        confirmingDelete = true
                    }
                } footer: {
                    Text("Deleting removes your account and everything you've "
                         + "uploaded. It can't be undone.")
                }

                Section {
                    LabeledContent("Version", value: Config.appVersion)
                }
            }
            .navigationTitle("Account")
            .alert("Delete your account?", isPresented: $confirmingDelete) {
                Button("Cancel", role: .cancel) {}
                Button("Delete", role: .destructive) { Task { await deleteAccount() } }
            } message: {
                Text("This permanently deletes your account, your uploads and your "
                     + "wallet balance. There's no way to get it back.")
            }
            .alert("Couldn't delete", isPresented: .constant(deleteError != nil)) {
                Button("OK") { deleteError = nil }
            } message: {
                Text(deleteError ?? "")
            }
        }
    }

    private func deleteAccount() async {
        struct Confirm: Encodable { let confirm: String }
        do {
            _ = try await APIClient.shared.post("api/economy/account/delete/",
                                                body: Confirm(confirm: "DELETE"),
                                                as: Empty.self)
            session.signOut()
        } catch {
            deleteError = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
    }
}
