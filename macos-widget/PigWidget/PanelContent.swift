import SwiftUI

@MainActor
final class PanelViewModel: ObservableObject {
  @Published var payload: PricesPayload?
  @Published var failed = false
  @Published var lastUpdated: Date?

  private var timer: Timer?

  init() {
    // Data changes 2x/day; 30 min is generous. Keeps the widget cheap on
    // every run (1 GET to our own endpoint).
    timer = Timer.scheduledTimer(withTimeInterval: 1800, repeats: true) { [weak self] _ in
      Task { @MainActor in self?.refresh() }
    }
  }

  func refresh() {
    PricesLoader.fetch { [weak self] result in
      Task { @MainActor in
        guard let self else { return }
        switch result {
        case .success(let payload):
          self.payload = payload
          self.failed = false
          self.lastUpdated = Date()
        case .failure:
          self.failed = true
        }
      }
    }
  }
}

// MARK: - Content

struct PanelContent: View {
  @ObservedObject var viewModel: PanelViewModel

  var body: some View {
    Group {
      if let payload = viewModel.payload {
        DashboardView(payload: payload)
      } else if viewModel.failed {
        VStack(spacing: 8) {
          Image(systemName: "wifi.exclamationmark")
            .foregroundStyle(Theme.down)
          Text("pig.maytek.co unreachable")
            .font(.system(.caption, design: .monospaced))
            .foregroundStyle(Theme.dim)
          Text("retrying every 30 min…")
            .font(.system(.caption2, design: .monospaced))
            .foregroundStyle(Theme.dim)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.background)
      } else {
        ProgressView()
          .frame(maxWidth: .infinity, maxHeight: .infinity)
          .background(Theme.background)
      }
    }
    .clipShape(RoundedRectangle(cornerRadius: Theme.corner))
    .overlay(
      RoundedRectangle(cornerRadius: Theme.corner)
        .stroke(Theme.border, lineWidth: 1)
    )
  }
}

// MARK: - Dashboard

private struct DashboardView: View {
  let payload: PricesPayload

  /// FATTENING PIGS only: per-head piglet prices are not USD/kg comparable.
  private var fattening: [Market] {
    payload.markets
      .filter { $0.category == "FATTENING PIGS" }
      .sorted { ($0.usdPerKg ?? 0) > ($1.usdPerKg ?? 0) }
  }

  private var regions: [(String, [Market])] {
    let grouped = Dictionary(grouping: fattening, by: { $0.region })
    return ["Europe", "America", "Asia", "Africa"]
      .compactMap { region in
        guard let rows = grouped[region], !rows.isEmpty else { return nil }
        return (region, rows)
      }
  }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 0) {
        header
        ForEach(regions, id: \.0) { region, rows in
          regionHeader(region, count: rows.count)
          ForEach(rows) { row in
            MarketRow(market: row)
          }
        }
        footer
      }
      .padding(.horizontal, 0)
    }
    .background(Theme.background)
  }

  private var header: some View {
    VStack(alignment: .leading, spacing: 2) {
      HStack(spacing: 6) {
        Text("🐷 Pig Prices")
          .font(.system(size: 14, weight: .bold))
          .foregroundStyle(Theme.text)
        Spacer()
        Text("USD/kg")
          .font(Theme.sectionFont)
          .foregroundStyle(Theme.dim)
      }
    }
    .padding(.horizontal, 14)
    .padding(.top, 16)
    .padding(.bottom, 10)
  }

  private func regionHeader(_ region: String, count: Int) -> some View {
    HStack {
      Text(region.uppercased())
        .font(Theme.sectionFont)
        .foregroundStyle(Theme.dim)
      Spacer()
      Text("\(count)")
        .font(Theme.sectionFont)
        .foregroundStyle(Theme.faint)
    }
    .padding(.horizontal, 14)
    .padding(.top, 12)
    .padding(.bottom, 4)
  }

  private var footer: some View {
    VStack(alignment: .leading, spacing: 2) {
      Rectangle().fill(Theme.border).frame(height: 0.5)
        .padding(.horizontal, 14)
      Text("updated \(payload.generatedAt.suffix(16)) UTC · \(payload.totalHistoryRows) history rows · refreshes 2×/day")
        .font(Theme.obsFont)
        .foregroundStyle(Theme.faint)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }
  }
}

// MARK: - Row: flag+country | USD/kg | observation

private struct MarketRow: View {
  let market: Market

  var body: some View {
    HStack(alignment: .center, spacing: 8) {
      // Column 1: flag + country
      HStack(spacing: 6) {
        Text(Theme.flagEmoji(market.flag))
          .font(.system(size: 13))
        Text(market.country)
          .font(Theme.rowFont)
          .foregroundStyle(Theme.text)
          .lineLimit(1)
      }
      .frame(width: 148, alignment: .leading)

      // Column 2: USD/kg (tabular digits, tinted by direction)
      Text(priceText)
        .font(Theme.monoFont)
        .monospacedDigit()
        .foregroundStyle(priceColor)
        .frame(width: 62, alignment: .trailing)

      // Column 3: observation (source · basis · unit)
      Text(observation)
        .font(Theme.obsFont)
        .foregroundStyle(Theme.dim)
        .lineLimit(1)
        .truncationMode(.tail)
        .frame(maxWidth: .infinity, alignment: .leading)

      // Direction arrow carries the variation without a 4th column
      if market.wentDown {
        Image(systemName: "arrow.down.right")
          .font(.system(size: 9, weight: .bold))
          .foregroundStyle(Theme.down.opacity(0.9))
      } else if market.wentUp {
        Image(systemName: "arrow.up.right")
          .font(.system(size: 9, weight: .bold))
          .foregroundStyle(Theme.up.opacity(0.9))
      }
    }
    .padding(.horizontal, 14)
    .frame(height: 22)
    .help(helpText)
  }

  private var priceText: String {
    if let usd = market.usdPerKg {
      String(format: "%.2f", usd)
    } else {
      "—"
    }
  }

  private var priceColor: Color {
    if market.usdPerKg == nil { return Theme.dim }
    if market.variationSuspect { return Theme.dim } // glitchy pig333 data: don't dramatize
    if market.wentDown { return Theme.down.opacity(0.95) }
    if market.wentUp { return Theme.up.opacity(0.95) }
    return Theme.text
  }

  private var observation: String {
    var parts = [market.reference]
    if market.unit.lowercased() != "kg" { parts.append(market.unit) }
    if market.variationSuspect { parts.append("⚠︎") }
    return parts.joined(separator: " · ")
  }

  private var helpText: String {
    var lines = [
      "\(market.country) — \(market.reference)",
      "\(market.price) \(market.currency)/\(market.unit) (\(market.priceDate))",
    ]
    if let v = market.variationPercent, !market.variationSuspect {
      lines.append("week change: \(market.wentDown ? "-" : "+")\(String(format: "%.1f", v))%")
    } else if market.variationSuspect {
      lines.append("pig333 variation data suspect this week")
    }
    return lines.joined(separator: "\n")
  }
}