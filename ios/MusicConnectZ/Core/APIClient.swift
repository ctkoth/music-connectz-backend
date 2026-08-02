import Foundation

enum APIError: LocalizedError, Equatable {
    case offline
    case unauthorized
    /// The backend's tier gate. 402 carries the feature and the tier that
    /// unlocks it, so the UI can go straight to the upgrade screen.
    case paymentRequired(detail: String, feature: String?, tier: String?)
    case server(status: Int, detail: String)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .offline:
            return "You're offline."
        case .unauthorized:
            return "Please sign in again."
        case .paymentRequired(let detail, _, _):
            return detail
        case .server(_, let detail):
            return detail
        case .decoding(let what):
            return "Couldn't read the response (\(what))."
        }
    }
}

/// Thin async wrapper over the Music ConnectZ REST API.
///
/// One rule worth keeping: a 401 triggers exactly ONE refresh-and-retry. Looping
/// on refresh is how a client ends up hammering the auth endpoint after a
/// password change, and the second 401 is the honest answer — the session is
/// gone, send the user to sign-in.
actor APIClient {
    static let shared = APIClient()

    private let session: URLSession
    private let decoder: JSONDecoder
    private var refreshTask: Task<Bool, Never>?

    init(session: URLSession = .shared) {
        self.session = session
        self.decoder = JSONDecoder()
    }

    // MARK: - Public

    @discardableResult
    func get<T: Decodable>(_ path: String, query: [String: String] = [:], as type: T.Type) async throws -> T {
        try await send(path, method: "GET", query: query, body: Optional<Empty>.none, as: type)
    }

    @discardableResult
    func post<B: Encodable, T: Decodable>(_ path: String, body: B, as type: T.Type) async throws -> T {
        try await send(path, method: "POST", query: [:], body: body, as: type)
    }

    @discardableResult
    func patch<B: Encodable, T: Decodable>(_ path: String, body: B, as type: T.Type) async throws -> T {
        try await send(path, method: "PATCH", query: [:], body: body, as: type)
    }

    // MARK: - Core

    private func send<B: Encodable, T: Decodable>(
        _ path: String, method: String, query: [String: String], body: B?, as type: T.Type,
        isRetry: Bool = false
    ) async throws -> T {
        let request = try build(path, method: method, query: query, body: body)
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError where error.code == .notConnectedToInternet {
            throw APIError.offline
        }

        guard let http = response as? HTTPURLResponse else {
            throw APIError.server(status: 0, detail: "No response from the server.")
        }

        switch http.statusCode {
        case 200..<300:
            if T.self == Empty.self { return Empty() as! T }
            do {
                return try decoder.decode(T.self, from: data)
            } catch {
                throw APIError.decoding(String(describing: T.self))
            }

        case 401:
            // Anonymous calls (login, register, catalogs) must not trigger a
            // refresh — there's nothing to refresh, and doing so would mask a
            // wrong password as a session problem.
            guard !isRetry, TokenStore.refresh != nil else {
                TokenStore.clear()
                throw APIError.unauthorized
            }
            guard await refreshAccessToken() else {
                TokenStore.clear()
                throw APIError.unauthorized
            }
            return try await send(path, method: method, query: query, body: body,
                                  as: type, isRetry: true)

        case 402:
            let payload = try? JSONDecoder().decode(GateResponse.self, from: data)
            throw APIError.paymentRequired(
                detail: payload?.detail ?? "That needs an upgrade.",
                feature: payload?.feature, tier: payload?.tier)

        default:
            throw APIError.server(status: http.statusCode, detail: Self.detail(from: data, status: http.statusCode))
        }
    }

    private func build<B: Encodable>(_ path: String, method: String, query: [String: String], body: B?) throws -> URLRequest {
        var components = URLComponents(
            url: Config.baseURL.appendingPathComponent(path),
            resolvingAgainstBaseURL: false)!
        if !query.isEmpty {
            components.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        var request = URLRequest(url: components.url!)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token = TokenStore.access {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
        }
        return request
    }

    /// Coalesced so twelve concurrent 401s produce one refresh, not twelve.
    private func refreshAccessToken() async -> Bool {
        if let existing = refreshTask { return await existing.value }
        let task = Task<Bool, Never> { [session] in
            guard let refresh = TokenStore.refresh else { return false }
            var request = URLRequest(url: Config.baseURL.appendingPathComponent("api/auth/refresh/"))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONEncoder().encode(["refresh": refresh])
            guard let (data, response) = try? await session.data(for: request),
                  let http = response as? HTTPURLResponse, http.statusCode == 200,
                  let payload = try? JSONDecoder().decode(RefreshResponse.self, from: data)
            else { return false }
            TokenStore.access = payload.access
            if let rotated = payload.refresh { TokenStore.refresh = rotated }
            return true
        }
        refreshTask = task
        let result = await task.value
        refreshTask = nil
        return result
    }

    /// DRF speaks several error dialects. Pull out something a human can read
    /// instead of showing a raw JSON blob.
    static func detail(from data: Data, status: Int) -> String {
        guard let object = try? JSONSerialization.jsonObject(with: data) else {
            return "Something went wrong (\(status))."
        }
        if let dict = object as? [String: Any] {
            if let detail = dict["detail"] as? String { return detail }
            // Field errors: {"username": ["already taken"]}
            for (_, value) in dict {
                if let list = value as? [Any], let first = list.first as? String { return first }
                if let text = value as? String { return text }
            }
        }
        if let list = object as? [Any], let first = list.first as? String { return first }
        return "Something went wrong (\(status))."
    }
}

// MARK: - Wire types

struct Empty: Codable {}

struct RefreshResponse: Decodable {
    let access: String
    let refresh: String?
}

struct GateResponse: Decodable {
    let detail: String?
    let feature: String?
    let tier: String?
}
