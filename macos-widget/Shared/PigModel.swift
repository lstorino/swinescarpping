import Foundation

// MARK: - API model (mirrors backend latest_payload())

struct PricesPayload: Decodable {
  let generatedAt: String
  let totalHistoryRows: Int
  let markets: [Market]
}

struct Market: Decodable, Identifiable {
  let marketId: Int
  let priceDate: String
  let scrapedAt: String
  let price: Double
  let currency: String
  let unit: String
  let usdPerKg: Double?
  let reference: String
  let variation: String?
  let delta: String?
  let deltaClass: String?
  let country: String
  let flag: String
  let region: String
  let category: String

  var id: Int { marketId }

  enum CodingKeys: String, CodingKey {
    case marketId = "market_id"
    case priceDate = "price_date"
    case scrapedAt = "scraped_at"
    case price, currency, unit
    case usdPerKg = "usd_per_kg"
    case reference, variation, delta
    case deltaClass = "delta_class"
    case country, flag, region, category
  }

  /// Variation % from pig333 (their own math — occasionally glitchy).
  var variationPercent: Double? {
    guard let variation,
          let digits = variation.split(separator: "%").first.map(String.init),
          let v = Double(digits) else { return nil }
    return v
  }

  /// true when the market's price went DOWN since the previous published value.
  var wentDown: Bool { deltaClass?.contains("down") == true }
  var wentUp: Bool { deltaClass?.contains("up") == true }

  /// pig333's 99.9% KRW artifact detector: a |variation| >= 50% is almost
  /// certainly their delta/current bug, not a real market move.
  var variationSuspect: Bool {
    guard let v = variationPercent else { return false }
    return abs(v) >= 50
  }
}

// MARK: - Loader

enum PricesLoader {
  /// Debug hook: PIG_API_BASE overrides the production base (same idea as
  /// NESTOR_API_BASE in the Nestor widget).
  private static var apiBase: String {
    ProcessInfo.processInfo.environment["PIG_API_BASE"] ?? Secrets.apiBase
  }

  static func fetch(completion: @escaping (Result<PricesPayload, Error>) -> Void) {
    let url = URL(string: "\(apiBase)/prices.json?token=\(Secrets.token)")!
    var request = URLRequest(url: url)
    request.timeoutInterval = 15
    URLSession.shared.dataTask(with: request) { data, _, error in
      if let error { return completion(.failure(error)) }
      guard let data,
            let payload = try? JSONDecoder().decode(PricesPayload.self, from: data) else {
        return completion(.failure(NSError(domain: "PigWidget", code: 1,
                                           userInfo: [NSLocalizedDescriptionKey: "invalid response"])))
      }
      completion(.success(payload))
    }.resume()
  }
}