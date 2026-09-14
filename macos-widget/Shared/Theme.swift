import SwiftUI

/// Dark, financial-terminal palette — visually consistent with the NESTOR
/// panel so the two widgets read as a family on the desktop.
enum Theme {
  static let background = Color(nsColor: NSColor(red: 0.07, green: 0.07, blue: 0.08, alpha: 1))
  static let border = Color.white.opacity(0.08)
  static let corner: CGFloat = 12

  static let text = Color.white.opacity(0.92)
  static let dim = Color.white.opacity(0.45)
  static let faint = Color.white.opacity(0.25)

  static let up = Color(red: 0.37, green: 0.84, blue: 0.48)    // green
  static let down = Color(red: 1.0, green: 0.42, blue: 0.38)   // red
  static let accent = Color(red: 0.88, green: 0.31, blue: 0.18) // pig terracotta

  /// Tabular monospaced digits so the USD/kg column never jitters on refresh.
  static let monoFont = Font.system(size: 12, weight: .semibold, design: .monospaced)
  static let rowFont = Font.system(size: 12, weight: .regular)
  static let obsFont = Font.system(size: 10, weight: .regular)
  static let sectionFont = Font.system(size: 10, weight: .semibold)

  /// Maps an ISO country code to an emoji flag — zero image assets, zero
  /// network, renders at any size. Fallback is a neutral flag.
  static func flagEmoji(_ code: String) -> String {
    guard code.count == 2 else { return "🏳️" }
    let base: UInt32 = 127397 // regional indicator A minus 'A' (65)
    var scalars = ""
    for ch in code.uppercased().unicodeScalars where ch.value >= 65 && ch.value <= 90 {
      guard let combined = UnicodeScalar(base + ch.value - 65) else { return "🏳️" }
      scalars.unicodeScalars.append(combined)
    }
    return scalars.count == 2 ? scalars : "🏳️"
  }
}