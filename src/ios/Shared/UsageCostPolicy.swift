import Foundation

/// All token buckets in StoredTokenUsage are disjoint (fresh input excludes
/// cache read/write). Unknown cache rates must not silently become zero.
enum UsageCostPolicy {
    static func estimate(input: Int, output: Int, read: Int, write: Int,
                         inputRate: Double?, outputRate: Double?,
                         readRate: Double?, writeRate: Double?) -> Double? {
        var result = 0.0
        for (tokens, rate) in [(input, inputRate), (output, outputRate),
                               (read, readRate), (write, writeRate)] {
            guard tokens >= 0 else { return nil }
            if tokens == 0 { continue }
            guard let rate, rate.isFinite, rate >= 0 else { return nil }
            result += Double(tokens) * rate / 1_000_000
        }
        return result.isFinite ? result : nil
    }

    static func display(_ usd: Double?, currency: String, usdToCNY: Double) -> String {
        guard let usd, usd.isFinite, usd >= 0 else { return "暂无价格" }
        if currency == "CNY" {
            guard usdToCNY.isFinite, usdToCNY > 0 else { return "请设置参考汇率" }
            return String(format: "¥%.4f", usd * usdToCNY)
        }
        return String(format: "$%.4f", usd)
    }
}
