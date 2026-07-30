import Foundation

// Field names mirror the API exactly (snake_case via CodingKeys) so a change on
// the backend fails to decode here loudly instead of silently producing an empty
// screen. Anything the server may omit is Optional or defaulted — a missing key
// should never take down a whole tab.

// MARK: - Account

struct User: Codable, Identifiable, Equatable {
    let id: Int
    let username: String
    let email: String
    var phone: String = ""
    var avatarURL: String = ""
    var isOwner: Bool = false
    var tier: String = "free"
    var spinaz: Int = 0
    var energy: Int = 0
    var onboarded: Bool = false
    var personas: [String] = []
    var genres: [String] = []
    var nationalities: [String] = []
    var age: Int?
    var zodiac: String?

    enum CodingKeys: String, CodingKey {
        case id, username, email, phone, tier, spinaz, energy, onboarded
        case personas, genres, nationalities, age, zodiac
        case avatarURL = "avatar_url"
        case isOwner = "is_owner"
    }
}

struct AuthResponse: Decodable {
    let user: User
    let access: String
    let refresh: String
}

struct LoginRequest: Encodable {
    let identifier: String
    let password: String
}

struct RegisterRequest: Encodable {
    let username: String
    let email: String
    let password: String
}

/// What the native Sign in with Apple flow posts to /api/auth/oauth/apple/.
/// The backend verifies this against Apple's public keys — the app never claims
/// an identity the server hasn't independently checked.
struct AppleSignInRequest: Encodable {
    let id_token: String
}

// MARK: - PersonaZ

struct PersonaCatalog: Decodable {
    let personas: [Persona]
}

struct Persona: Decodable, Identifiable, Equatable {
    var id: String { key }
    let key: String
    let name: String
    let emoji: String
    let label: String
    let blurb: String
    let since: String
    let skillCount: Int
    let categories: [SkillCategory]

    enum CodingKeys: String, CodingKey {
        case key, name, emoji, label, blurb, since, categories
        case skillCount = "skill_count"
    }
}

struct SkillCategory: Decodable, Equatable, Identifiable {
    var id: String { name }
    let name: String
    let skills: [Skill]
}

struct Skill: Decodable, Equatable, Identifiable {
    var id: String { key }
    let key: String
    let label: String
    /// The "Any String 🎸" style wildcard — means "I play something in this
    /// family" rather than one specific instrument.
    let any: Bool
}

// MARK: - GenreZ

struct GenreCatalog: Decodable {
    let genres: [Genre]
    let count: Int
}

struct Genre: Decodable, Identifiable, Equatable {
    var id: String { key }
    let key: String
    let name: String
    let emoji: String
    let since: String
    /// "music" or "screen" — ReelZ/EpisodeZ/MovieZ use the screen list.
    let kind: String
    let alsoASkill: Bool

    enum CodingKeys: String, CodingKey {
        case key, name, emoji, since, kind
        case alsoASkill = "also_a_skill"
    }
}

// MARK: - BodieZ

struct BodieZCatalog: Decodable {
    let equipment: [CatalogEntry]
    let muscleGroups: [CatalogEntry]
    let goals: [CatalogEntry]
    let exerciseCount: Int

    enum CodingKeys: String, CodingKey {
        case equipment, goals
        case muscleGroups = "muscle_groups"
        case exerciseCount = "exercise_count"
    }
}

/// Every BodieZ vocabulary list — equipment, muscles, goals — comes back as
/// {key, name, emoji}. Muscle groups add `region`, which the others omit.
struct CatalogEntry: Decodable, Identifiable, Equatable {
    var id: String { key }
    let key: String
    let name: String
    let emoji: String
    let region: String?

    var display: String { "\(emoji) \(name)" }
}

struct Exercise: Decodable, Identifiable, Equatable {
    let id: Int
    let key: String
    let name: String
    let muscle: String
    let secondary: [String]
    let equipment: [String]
    let pattern: String
    let difficulty: String
    let instructions: String

    enum CodingKeys: String, CodingKey {
        case id, key, name, muscle, secondary, equipment, pattern, difficulty, instructions
    }
}

struct ExerciseList: Decodable {
    let exercises: [Exercise]
}

struct Routine: Decodable, Identifiable, Equatable {
    let id: Int
    let name: String
    let goal: String
    let split: String
    let bucket: String
    let bucketLabel: String
    let daysPerWeek: Int
    let exerciseCount: Int
    let estimatedMinutes: Int
    let owner: String

    enum CodingKeys: String, CodingKey {
        case id, name, goal, split, bucket, owner
        case bucketLabel = "bucket_label"
        case daysPerWeek = "days_per_week"
        case exerciseCount = "exercise_count"
        case estimatedMinutes = "estimated_minutes"
    }
}

struct RoutineList: Decodable {
    let routines: [Routine]
}
