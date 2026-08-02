import SwiftUI

/// BodieZ, the way the routine builder works: toggle the equipment you actually
/// have, and the library filters to what you can do today. The filtering happens
/// server-side (`?equipment=`) because the any-of requirement logic lives there —
/// a goblet squat needs a kettlebell OR a dumbbell, and reimplementing that rule
/// in two languages is how the two drift apart.
struct BodieZLibraryView: View {
    @State private var catalog: BodieZCatalog?
    @State private var exercises: [Exercise] = []
    @State private var selectedEquipment: Set<String> = []
    @State private var selectedMuscles: Set<String> = []
    @State private var loading = true
    @State private var loadError: String?

    var body: some View {
        NavigationStack {
            Group {
                if loading && catalog == nil {
                    ProgressView()
                } else if let loadError, catalog == nil {
                    ContentUnavailableView("Couldn't load BodieZ", systemImage: "wifi.slash",
                                           description: Text(loadError))
                } else {
                    content
                }
            }
            .navigationTitle("BodieZ")
            .task { await loadCatalog() }
        }
    }

    private var content: some View {
        List {
            if let catalog {
                Section {
                    ChipGrid(entries: catalog.equipment, selection: $selectedEquipment)
                } header: {
                    Text("What you've got")
                } footer: {
                    Text("Bodyweight is always available — you never have to toggle it.")
                }

                Section("Target muscles") {
                    ChipGrid(entries: catalog.muscleGroups, selection: $selectedMuscles)
                }
            }

            Section("\(exercises.count) exercises") {
                if exercises.isEmpty && !loading {
                    Text("Nothing matches that combination yet.")
                        .foregroundStyle(.secondary)
                }
                ForEach(exercises) { exercise in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(exercise.name).font(.headline)
                        Text(exercise.muscle.replacingOccurrences(of: "-", with: " ").capitalized)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 2)
                }
            }
        }
        .listStyle(.insetGrouped)
        // Debounced in effect: SwiftUI coalesces rapid toggles into one task
        // because each change cancels the previous one.
        .task(id: filterKey) { await loadExercises() }
    }

    private var filterKey: String {
        selectedEquipment.sorted().joined(separator: ",") + "|"
            + selectedMuscles.sorted().joined(separator: ",")
    }

    private func loadCatalog() async {
        do {
            catalog = try await APIClient.shared.get("api/bodiez/catalog/", as: BodieZCatalog.self)
        } catch {
            loadError = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
        loading = false
    }

    private func loadExercises() async {
        var query: [String: String] = [:]
        if !selectedEquipment.isEmpty {
            query["equipment"] = selectedEquipment.sorted().joined(separator: ",")
        }
        if !selectedMuscles.isEmpty {
            query["muscles"] = selectedMuscles.sorted().joined(separator: ",")
        }
        loading = true
        defer { loading = false }
        if let list = try? await APIClient.shared.get("api/bodiez/exercises/", query: query,
                                                      as: ExerciseList.self) {
            exercises = list.exercises
        }
    }
}

private struct ChipGrid: View {
    let entries: [CatalogEntry]
    @Binding var selection: Set<String>

    private let columns = [GridItem(.adaptive(minimum: 108), spacing: 8)]

    var body: some View {
        LazyVGrid(columns: columns, spacing: 8) {
            ForEach(entries) { entry in
                let on = selection.contains(entry.key)
                Button {
                    if on { selection.remove(entry.key) } else { selection.insert(entry.key) }
                } label: {
                    Text(entry.display)
                        .font(.caption)
                        .lineLimit(1)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                        .background(on ? AnyShapeStyle(.tint) : AnyShapeStyle(.quaternary),
                                    in: Capsule())
                        .foregroundStyle(on ? .white : .primary)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.vertical, 4)
    }
}
