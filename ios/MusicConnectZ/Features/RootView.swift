import SwiftUI

/// Routing lives in exactly one place: loading → sign-in → tour → the app.
struct RootView: View {
    @EnvironmentObject private var session: Session

    var body: some View {
        switch session.state {
        case .loading:
            ProgressView("Loading…")

        case .signedOut:
            SignInView()

        case .signedIn:
            if session.needsTour {
                TourView()
            } else {
                MainTabs()
            }
        }
    }
}

struct MainTabs: View {
    var body: some View {
        TabView {
            PersonaPickerView()
                .tabItem { Label("PersonaZ", systemImage: "person.crop.circle") }

            BodieZLibraryView()
                .tabItem { Label("BodieZ", systemImage: "figure.strengthtraining.traditional") }

            AccountView()
                .tabItem { Label("Account", systemImage: "gearshape") }
        }
    }
}
