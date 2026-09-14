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
  /// Regional Indicator A..Z = U+1F1E6..U+1F1FF, i.e. 0x1F1E6 + (letter - 'A').
  static func flagEmoji(_ code: String) -> String {
    let upper = code.uppercased()
    guard upper.count == 2,
          let first = upper.first?.unicodeScalars.first,
          let last = upper.last?.unicodeScalars.first,
          (65...90).contains(first.value), (65...90).contains(last.value),
          let s1 = UnicodeScalar(0x1F1E6 + first.value - 65),
          let s2 = UnicodeScalar(0x1F1E6 + last.value - 65) else { return "🏳️" }
    return String(String.UnicodeScalarView([s1, s2]))
  }
}