import SwiftUI

/// The real PersonaZ catalog — 11 personas, 415 skills — served by
/// GET /api/economy/personaz/. The catalog is public, so this screen loads
/// before the member has picked anything.
struct PersonaPickerView: View {
    @EnvironmentObject private var session: Session
    @State private var personas: [Persona] = []
    @State private var loadError: String?
    @State private var loading = true

    var body: some View {
        NavigationStack {
            Group {
                if loading {
                    ProgressView()
                } else if let loadError {
                    ContentUnavailableView("Couldn't load PersonaZ", systemImage: "wifi.slash",
                                           description: Text(loadError))
                } else {
                    List(personas) { persona in
                        NavigationLink {
                            SkillListView(persona: persona)
                        } label: {
                            PersonaRow(persona: persona,
                                       selected: session.user?.personas.contains(persona.key) ?? false)
                        }
                    }
                    .listStyle(.insetGrouped)
                }
            }
            .navigationTitle("PersonaZ")
            .task { await load() }
            .refreshable { await load() }
        }
    }

    private func load() async {
        loading = personas.isEmpty
        do {
            let catalog = try await APIClient.shared.get("api/economy/personaz/",
                                                         as: PersonaCatalog.self)
            personas = catalog.personas
            loadError = nil
        } catch {
            loadError = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
        loading = false
    }
}

private struct PersonaRow: View {
    let persona: Persona
    let selected: Bool

    var body: some View {
        HStack(spacing: 12) {
            Text(persona.emoji).font(.title2)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(persona.name).font(.headline)
                    if persona.since == "2.2" {
                        Text("2.2")
                            .font(.caption2.bold())
                            .padding(.horizontal, 5).padding(.vertical, 1)
                            .background(.tint.opacity(0.15), in: Capsule())
                    }
                }
                Text(persona.blurb)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                Text("\(persona.skillCount) skills")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Spacer()
            if selected {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.tint)
            }
        }
        .padding(.vertical, 4)
    }
}

/// Skills grouped by category, the way the catalog ships them. The wildcard
/// entries ("Any String 🎸") are marked, because picking one means something
/// different from picking a specific instrument.
struct SkillListView: View {
    let persona: Persona

    var body: some View {
        List {
            ForEach(persona.categories) { category in
                Section(category.name) {
                    ForEach(category.skills) { skill in
                        HStack {
                            Text(skill.label)
                            if skill.any {
                                Spacer()
                                Text("any")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle(persona.name)
        .navigationBarTitleDisplayMode(.inline)
    }
}
