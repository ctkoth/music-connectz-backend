import XCTest
@testable import MusicConnectZ

/// These fixtures are copied from real responses, not invented. If the backend
/// renames a field, these fail — which is the point. A client that decodes
/// leniently just shows an empty screen and nobody finds out for a week.
final class DecodingTests: XCTestCase {

    private func decode<T: Decodable>(_ json: String, as type: T.Type) throws -> T {
        try JSONDecoder().decode(type, from: Data(json.utf8))
    }

    func testUserDecodesFromMeEndpoint() throws {
        let user = try decode("""
        {"id": 7, "username": "corey", "email": "c@example.com", "phone": "",
         "avatar_url": "", "is_owner": true, "tier": "debug", "spinaz": 40,
         "energy": 3, "onboarded": true, "personas": ["artist", "developer"],
         "genres": ["Trap"], "nationalities": [], "birthday": null,
         "age": null, "zodiac": null}
        """, as: User.self)

        XCTAssertEqual(user.username, "corey")
        XCTAssertTrue(user.isOwner)
        XCTAssertEqual(user.personas, ["artist", "developer"])
        XCTAssertNil(user.age)
    }

    func testPersonaCatalogDecodesNestedSkills() throws {
        let catalog = try decode("""
        {"personas": [{"key": "artist", "name": "Artist", "emoji": "🎤",
          "label": "Artist 🎤", "blurb": "You make the music.", "since": "2.2",
          "skill_count": 97,
          "categories": [{"name": "String Instruments", "skills": [
            {"key": "Any String", "label": "Any String 🎸", "any": true},
            {"key": "Banjo", "label": "Banjo 🎸", "any": false}]}]}],
         "aliases": {}, "rules": {}}
        """, as: PersonaCatalog.self)

        let artist = try XCTUnwrap(catalog.personas.first)
        XCTAssertEqual(artist.skillCount, 97)
        XCTAssertEqual(artist.since, "2.2")
        XCTAssertTrue(artist.categories[0].skills[0].any,
                      "the wildcard 'Any String' must survive decoding — it means "
                      + "something different from a specific instrument")
        XCTAssertFalse(artist.categories[0].skills[1].any)
    }

    func testGenreDecodesBothKinds() throws {
        let catalog = try decode("""
        {"genres": [
          {"key": "Trap", "name": "Trap", "emoji": "🏚️", "since": "2.2",
           "kind": "music", "also_a_skill": true},
          {"key": "Horror", "name": "Horror", "emoji": "🔪", "since": "2.4",
           "kind": "screen", "also_a_skill": false}],
         "kind": null, "kinds": [], "v22": [], "count": 2, "rules": {}}
        """, as: GenreCatalog.self)

        XCTAssertEqual(catalog.count, 2)
        XCTAssertEqual(catalog.genres.map(\.kind), ["music", "screen"])
        XCTAssertTrue(catalog.genres[0].alsoASkill)
    }

    func testBodieZCatalogEntriesUseNameAndEmojiNotLabel() throws {
        let catalog = try decode("""
        {"equipment": [{"key": "barbell", "name": "Barbell", "emoji": "🏋️"}],
         "muscle_groups": [{"key": "chest", "name": "Chest", "emoji": "💪",
                            "region": "upper"}],
         "goals": [{"key": "strength", "name": "Strength", "emoji": "🥇"}],
         "movement_patterns": [], "difficulties": [], "splits": {},
         "buckets": [], "exercise_count": 98, "tiers": {}}
        """, as: BodieZCatalog.self)

        XCTAssertEqual(catalog.exerciseCount, 98)
        XCTAssertEqual(catalog.equipment.first?.display, "🏋️ Barbell")
        XCTAssertEqual(catalog.muscleGroups.first?.region, "upper")
        XCTAssertNil(catalog.equipment.first?.region,
                     "only muscle groups carry a region; the others omit it")
    }

    func testTourReplyPutsCoreysTextUnderExplain() throws {
        let reply = try decode("""
        {"step": "welcome", "choice": "1",
         "explain": {"text": "That's the one.", "source": "builtin",
                     "voice": "corey-gpt", "cost_cents": 0},
         "highlight": null, "route": null,
         "next": {"key": "personaz", "index": 2, "total": 6,
                  "screen": null, "route": null, "title": "Who are you here as?",
                  "blurb": "Pick what you actually do.", "highlight": null,
                  "input": {}, "picker": null, "terminal": false, "options": []},
         "progress": {"track": "make", "step": "personaz", "done": [],
                      "done_count": 1, "total": 6, "answers": {},
                      "skipped": false, "completed": false, "completed_at": null}}
        """, as: TourReply.self)

        XCTAssertEqual(reply.explain.text, "That's the one.")
        XCTAssertEqual(reply.next?.key, "personaz")
        XCTAssertFalse(reply.isFinished)
    }

    func testTourWithNoNextStepIsFinished() throws {
        let reply = try decode("""
        {"explain": {"text": "You're set.", "source": "corey-gpt"}, "next": null}
        """, as: TourReply.self)
        XCTAssertTrue(reply.isFinished)
    }

    func testTourProgressDrivesRoutingNotUserOnboarded() throws {
        let skipped = try decode("""
        {"skipped": true, "completed": false}
        """, as: TourProgress.self)
        XCTAssertTrue(skipped.isFinished,
                      "a member who skipped must not be shown the tour again")
    }
}

final class APIErrorTests: XCTestCase {

    func testDetailPrefersTheDetailKey() {
        let data = Data(#"{"detail": "No active account found."}"#.utf8)
        XCTAssertEqual(APIClient.detail(from: data, status: 401),
                       "No active account found.")
    }

    func testDetailFallsBackToFirstFieldError() {
        let data = Data(#"{"username": ["Already taken."]}"#.utf8)
        XCTAssertEqual(APIClient.detail(from: data, status: 400), "Already taken.")
    }

    func testDetailSurvivesNonJSONBody() {
        let data = Data("<html>502 Bad Gateway</html>".utf8)
        XCTAssertEqual(APIClient.detail(from: data, status: 502),
                       "Something went wrong (502).")
    }

    func testGateResponseCarriesFeatureAndTier() throws {
        let gate = try JSONDecoder().decode(GateResponse.self, from: Data("""
        {"detail": "Gym locations is a Premium feature.",
         "feature": "Gym locations", "tier": "premium"}
        """.utf8))
        XCTAssertEqual(gate.tier, "premium")
        XCTAssertEqual(gate.feature, "Gym locations")
    }
}
