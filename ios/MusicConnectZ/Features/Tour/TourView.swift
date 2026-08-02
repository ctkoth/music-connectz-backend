import SwiftUI

// The tour ships every option's written explanation inside the payload, so a
// tap renders instantly and still renders with no network. A live Corey reply
// replaces it when the model is reachable. That's why `explain` is not optional
// here — the offline path is the design, not a fallback.

struct TourStep: Decodable, Identifiable {
    var id: String { key }
    let key: String
    let index: Int?
    let total: Int?
    let title: String
    let blurb: String
    let terminal: Bool
    let options: [TourOption]
}

struct TourOption: Decodable, Identifiable {
    var id: String { key }
    let key: String
    let reply: String
    let label: String
    let explain: String
}

struct TourPayload: Decodable {
    let steps: [TourStep]
    let resume: String
    let progress: TourProgress?
}

/// The tour tracks its own completion. Note this is NOT `user.onboarded` —
/// that flag is the economy signup grant and gets set the first time a member
/// is credited, which has nothing to do with whether they've seen the tour.
/// Routing on it would replay the tour forever for anyone who skipped.
struct TourProgress: Decodable {
    let skipped: Bool
    let completed: Bool

    var isFinished: Bool { skipped || completed }
}

struct TourAnswer: Encodable {
    let step: String
    let choice: String
}

/// The answer endpoint returns the next step in full, not just its key — so the
/// client never has to look it up, and a step the tour reaches dynamically works
/// even if it wasn't in the initial track payload.
struct TourReply: Decodable {
    let explain: TourExplain
    let next: TourStep?

    /// No `done` flag on the wire: the tour is over when there's no next step.
    var isFinished: Bool { next == nil }
}

struct TourExplain: Decodable {
    let text: String
    /// "corey-gpt" when the model answered live, "builtin" when it's the copy
    /// that shipped with the payload.
    let source: String
}

/// OmviardZ — Corey's guided tour, one highlighted option at a time.
///
/// Free, and it must stay free: charging for onboarding is how you lose someone
/// in the first five minutes.
struct TourView: View {
    @EnvironmentObject private var session: Session
    @State private var steps: [TourStep] = []
    @State private var currentKey: String?
    @State private var coreySays: String?
    @State private var busy = false
    @State private var loadError: String?

    private var step: TourStep? {
        steps.first { $0.key == currentKey } ?? steps.first
    }

    var body: some View {
        NavigationStack {
            Group {
                if steps.isEmpty && loadError == nil {
                    ProgressView("Getting Corey…")
                } else if let loadError {
                    ContentUnavailableView("Couldn't load the tour", systemImage: "wifi.slash",
                                           description: Text(loadError))
                } else if let step {
                    stepBody(step)
                }
            }
            .navigationTitle("OmviardZ")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Skip") { Task { await skip() } }
                }
            }
            .task { await load() }
        }
    }

    @ViewBuilder
    private func stepBody(_ step: TourStep) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let index = step.index, let total = step.total {
                    ProgressView(value: Double(index), total: Double(total))
                    Text("Step \(index) of \(total)")
                        .font(.caption).foregroundStyle(.secondary)
                }

                Text(step.title).font(.title2.bold())
                Text(step.blurb).foregroundStyle(.secondary)

                if let coreySays {
                    Text(coreySays)
                        .padding()
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.tint.opacity(0.10), in: RoundedRectangle(cornerRadius: 14))
                        .transition(.opacity)
                }

                ForEach(step.options) { option in
                    Button {
                        Task { await choose(step: step, option: option) }
                    } label: {
                        HStack {
                            Text(option.label).multilineTextAlignment(.leading)
                            Spacer()
                            Image(systemName: "chevron.right").font(.caption)
                        }
                        .padding()
                        .frame(maxWidth: .infinity)
                        .background(.quaternary, in: RoundedRectangle(cornerRadius: 14))
                    }
                    .buttonStyle(.plain)
                    .disabled(busy)
                }

                if step.terminal {
                    Button("Finish") { Task { await finish() } }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                        .frame(maxWidth: .infinity)
                }
            }
            .padding(20)
        }
    }

    private func load() async {
        // Session already fetched this to decide whether to show the tour at
        // all — reuse it rather than paying for the same payload twice.
        if let cached = session.tour {
            steps = cached.steps
            currentKey = cached.resume
            return
        }
        do {
            let payload = try await APIClient.shared.get("api/omviardz/tour/", as: TourPayload.self)
            steps = payload.steps
            currentKey = payload.resume
        } catch {
            loadError = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
    }

    private func choose(step: TourStep, option: TourOption) async {
        // Show the shipped explanation immediately — the network round trip is
        // an upgrade to this, never a prerequisite for it.
        withAnimation { coreySays = option.explain }
        busy = true
        defer { busy = false }

        guard let reply = try? await APIClient.shared.post(
            "api/omviardz/answer/",
            body: TourAnswer(step: step.key, choice: option.reply),
            as: TourReply.self) else { return }

        if !reply.explain.text.isEmpty {
            withAnimation { coreySays = reply.explain.text }
        }
        if let next = reply.next {
            // Steps can arrive that weren't in the initial track payload, so
            // fold the new one in rather than assuming it's already there.
            if !steps.contains(where: { $0.key == next.key }) { steps.append(next) }
            withAnimation { currentKey = next.key }
        } else {
            await finish()
        }
    }

    private func finish() async {
        session.markTourFinished()
        await session.refreshUser()
    }

    /// The backend remembers a skip so the tour doesn't ambush them next launch.
    private func skip() async {
        _ = try? await APIClient.shared.post("api/omviardz/skip/", body: Empty(), as: Empty.self)
        await finish()
    }
}
