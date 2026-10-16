//
//  AppLocalization.swift
//  MinisApp
//
//  [T-ios-inapp-language-string-localized] Makes the in-app language picker
//  actually apply to every localized string, not just some of them.
//
//  The problem
//  -----------
//  `Bundle.enableLanguageOverride()` (MinisApp.swift) swizzles
//  `Bundle.localizedString(forKey:value:table:)` so the in-app language choice
//  is honoured without an app restart. That works for `Text("…")` and UIKit,
//  which route through that ObjC method — but `String(localized:)` does NOT.
//
//  Measured, not assumed. With the swizzle installed:
//
//      NSLocalizedString("k")   -> Bundle.localizedString hits: 1
//      String(localized: "k")   -> Bundle.localizedString hits: 0
//
//  Three interception strategies were tried against a real bundle and all
//  three failed to redirect `String(localized:)`:
//    1. method swizzling `localizedString(forKey:value:table:)`   — bypassed
//    2. `object_setClass` onto a Bundle subclass overriding it    — bypassed
//    3. overriding `preferredLocalizations` / `localizations`     — bypassed
//  `String(localized:)` resolves the table natively inside Foundation and
//  never calls back into the ObjC entry point, so nothing installed on
//  `Bundle.main` can steer it. Setting `AppleLanguages` does work, but only
//  from the NEXT process launch — verified: `preferredLocalizations` does not
//  change within the running process.
//
//  What DOES work is the one documented seam: `String(localized:bundle:)`
//  honours an explicit bundle. Verified against `es.lproj` / `de.lproj` /
//  `en.lproj` — each returns that language's value.
//
//  The fix
//  -------
//  Route every call through `AppBundle.current`, which is the overridden
//  `.lproj` bundle when the user has picked a language in-app, and
//  `Bundle.main` otherwise. This is deliberately generic: it is keyed off
//  whatever language is selected, so de / fr / ja / ko / ru / zh-Hans /
//  zh-Hant / es all behave the same. Nothing here is Spanish-specific.
//

import Foundation

/// The bundle localized lookups should read from.
///
/// Mirrors `Bundle.main.languageBundle` (set by `Bundle.setLanguage(_:)`), so
/// the in-app picker and this helper can never disagree about which language is
/// active. Falls back to `Bundle.main` when no in-app override is set, which is
/// the normal case — the system language then applies exactly as before.
enum AppBundle {
    static var current: Bundle {
        Bundle.main.languageBundle ?? Bundle.main
    }
}

/// Localized string that follows the in-app language override.
///
/// Drop-in replacement for `String(localized:)`. Prefer this over
/// `String(localized:)` anywhere the result is shown to the user: the bare
/// form silently ignores the in-app language setting (see the file comment),
/// which is what produced mixed-language UI for users whose system language
/// differs from their in-app choice.
///
/// `Text("…")` does not need this — SwiftUI's `Text` routes through
/// `NSLocalizedString`, which the existing swizzle already covers.
///
/// - Parameters:
///   - key: the localization key, i.e. the English source string.
///   - comment: translator context, kept so `genstrings`-style extraction and
///     the String Catalog continue to see it.
func AppLocalized(_ key: String.LocalizationValue, comment: StaticString? = nil) -> String {
    String(localized: key, bundle: AppBundle.current, comment: comment)
}

/// `LocalizedStringResource` overload, for call sites that already hold a
/// resource (App Intents build these) rather than a literal key.
@available(iOS 16.0, *)
func AppLocalized(_ resource: LocalizedStringResource) -> String {
    // A LocalizedStringResource carries its own bundle reference, so it cannot
    // be re-pointed the way a literal key can. Resolve it as-is rather than
    // pretending the override applies.
    String(localized: resource)
}


// iOS 15.4 compatibility: real legacy views, not disabled availability checks.
import SwiftUI
import UIKit

struct MinisLabeledContent<Content: View, LabelView: View>: View {
    let content: Content
    let label: LabelView
    init(@ViewBuilder content: () -> Content, @ViewBuilder label: () -> LabelView) {
        self.content = content(); self.label = label()
    }
    init(_ title: String, @ViewBuilder content: () -> Content) where LabelView == Text {
        self.content = content(); self.label = Text(LocalizedStringKey(title))
    }
    init(_ title: String, value: String) where LabelView == Text, Content == Text {
        self.content = Text(value).foregroundColor(.secondary)
        self.label = Text(LocalizedStringKey(title))
    }
    var body: some View { HStack { label; Spacer(minLength: 12); content } }
}

struct MinisAnyShape: Shape {
    private let makePath: (CGRect) -> Path
    init<S: Shape>(_ shape: S) { makePath = { shape.path(in: $0) } }
    func path(in rect: CGRect) -> Path { makePath(rect) }
}

struct MinisUnevenRoundedRectangle: Shape {
    var topLeadingRadius: CGFloat = 0
    var bottomLeadingRadius: CGFloat = 0
    var bottomTrailingRadius: CGFloat = 0
    var topTrailingRadius: CGFloat = 0
    var style: RoundedCornerStyle = .continuous
    func path(in r: CGRect) -> Path {
        let limit = min(r.width, r.height) / 2
        let tl = max(0, min(topLeadingRadius, limit))
        let tr = max(0, min(topTrailingRadius, limit))
        let bl = max(0, min(bottomLeadingRadius, limit))
        let br = max(0, min(bottomTrailingRadius, limit))
        var p = Path()
        p.move(to: CGPoint(x: r.minX + tl, y: r.minY))
        p.addLine(to: CGPoint(x: r.maxX - tr, y: r.minY))
        p.addQuadCurve(to: CGPoint(x: r.maxX, y: r.minY + tr), control: CGPoint(x: r.maxX, y: r.minY))
        p.addLine(to: CGPoint(x: r.maxX, y: r.maxY - br))
        p.addQuadCurve(to: CGPoint(x: r.maxX - br, y: r.maxY), control: CGPoint(x: r.maxX, y: r.maxY))
        p.addLine(to: CGPoint(x: r.minX + bl, y: r.maxY))
        p.addQuadCurve(to: CGPoint(x: r.minX, y: r.maxY - bl), control: CGPoint(x: r.minX, y: r.maxY))
        p.addLine(to: CGPoint(x: r.minX, y: r.minY + tl))
        p.addQuadCurve(to: CGPoint(x: r.minX + tl, y: r.minY), control: CGPoint(x: r.minX, y: r.minY))
        p.closeSubpath(); return p
    }
}

private struct MinisGeometryPreference<T: Equatable>: PreferenceKey {
    static var defaultValue: T? { nil }
    static func reduce(value: inout T?, nextValue: () -> T?) { value = nextValue() ?? value }
}
private struct MinisFontWeight: ViewModifier {
    @Environment(\.font) var font
    let weight: Font.Weight
    func body(content: Content) -> some View { content.font((font ?? .body).weight(weight)) }
}

enum MinisToolbarBar: Equatable { case navigationBar, tabBar, bottomBar, automatic }
extension View {
    @ViewBuilder
    func minisOnGeometryChange<T: Equatable>(for type: T.Type, of transform: @escaping (GeometryProxy) -> T,
                                            action: @escaping (T) -> Void) -> some View {
        if #available(iOS 16.0, *) { self.onGeometryChange(for: type, of: transform, action: action) }
        else {
            self.background(GeometryReader { proxy in
                Color.clear.preference(key: MinisGeometryPreference<T>.self, value: transform(proxy))
            }).onPreferenceChange(MinisGeometryPreference<T>.self) { if let value = $0 { action(value) } }
        }
    }
    @ViewBuilder
    func minisContextMenu<Menu: View, Preview: View>(@ViewBuilder menuItems: () -> Menu,
                                                    @ViewBuilder preview: () -> Preview) -> some View {
        if #available(iOS 16.0, *) { self.contextMenu(menuItems: menuItems, preview: preview) }
        else { self.contextMenu(menuItems: menuItems) }
    }
    func minisContextMenu<Menu: View>(@ViewBuilder menuItems: () -> Menu) -> some View {
        self.contextMenu(menuItems: menuItems)
    }
    func minisFontWeight(_ weight: Font.Weight) -> some View { modifier(MinisFontWeight(weight: weight)) }
    @ViewBuilder
    func minisPersistentSystemOverlays(_ visibility: Visibility) -> some View {
        if #available(iOS 16.0, *) { self.persistentSystemOverlays(visibility) } else { self }
    }
    @ViewBuilder
    func minisToolbarVisibility(_ visibility: Visibility, for bar: MinisToolbarBar) -> some View {
        if #available(iOS 16.0, *) {
            switch bar {
            case .navigationBar: self.toolbar(visibility, for: .navigationBar)
            case .tabBar: self.toolbar(visibility, for: .tabBar)
            case .bottomBar: self.toolbar(visibility, for: .bottomBar)
            case .automatic: self.toolbar(visibility, for: .automatic)
            }
        } else { self.navigationBarHidden(bar == .navigationBar && visibility == .hidden) }
    }
    func minisDraggable(_ text: String) -> some View {
        self.onDrag { NSItemProvider(object: text as NSString) }
    }
    func minisDropDestination(for type: String.Type, action: @escaping ([String], CGPoint) -> Bool,
                               isTargeted: @escaping (Bool) -> Void = { _ in }) -> some View {
        self.onDrop(of: ["public.utf8-plain-text"], isTargeted: Binding(get: { false }, set: isTargeted)) { providers, point in
            let candidates = providers.filter { $0.canLoadObject(ofClass: NSString.self) }
            guard !candidates.isEmpty else { return false }
            let group = DispatchGroup(); let lock = NSLock(); var values: [String] = []
            for provider in candidates {
                group.enter()
                _ = provider.loadObject(ofClass: NSString.self) { object, _ in
                    if let value = object as? String { lock.lock(); values.append(value); lock.unlock() }
                    group.leave()
                }
            }
            group.notify(queue: .main) { _ = action(values, point) }
            return true
        }
    }
}

struct MinisHostingConfiguration<Content: View>: UIContentConfiguration {
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    func minSize(width: CGFloat? = nil, height: CGFloat? = nil) -> Self { self }
    func margins(_ edges: Edge.Set = .all, _ length: CGFloat) -> Self { self }
    func updated(for state: UIConfigurationState) -> Self { self }
    func makeContentView() -> UIView & UIContentView {
        if #available(iOS 16.0, *) {
            return UIHostingConfiguration { content }.minSize(width: 0, height: 0).margins(.all, 0).makeContentView()
        }
        return MinisHostingContentView(self)
    }
}
private final class MinisHostingContentView<Content: View>: UIView, UIContentView {
    private let host: UIHostingController<Content>
    var configuration: UIContentConfiguration {
        didSet {
            if let config = configuration as? MinisHostingConfiguration<Content> {
                host.rootView = config.content; host.view.invalidateIntrinsicContentSize(); invalidateIntrinsicContentSize()
            }
        }
    }
    init(_ config: MinisHostingConfiguration<Content>) {
        configuration = config; host = UIHostingController(rootView: config.content)
        super.init(frame: .zero)
        backgroundColor = .clear; host.view.backgroundColor = .clear
        host.view.translatesAutoresizingMaskIntoConstraints = false; addSubview(host.view)
        NSLayoutConstraint.activate([
            host.view.topAnchor.constraint(equalTo: topAnchor), host.view.bottomAnchor.constraint(equalTo: bottomAnchor),
            host.view.leadingAnchor.constraint(equalTo: leadingAnchor), host.view.trailingAnchor.constraint(equalTo: trailingAnchor)
        ])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }
    override var intrinsicContentSize: CGSize {
        host.sizeThatFits(in: CGSize(width: bounds.width > 0 ? bounds.width : UIScreen.main.bounds.width,
                                    height: CGFloat.greatestFiniteMagnitude))
    }
}


final class MinisBadgeCenter: @unchecked Sendable {
    static let shared = MinisBadgeCenter()
    func setBadgeCount(_ count: Int) async throws {
        await MainActor.run { UIApplication.shared.applicationIconBadgeNumber = count }
    }
    func setBadgeCount(_ count: Int, withCompletionHandler completion: ((Error?) -> Void)? = nil) {
        DispatchQueue.main.async { UIApplication.shared.applicationIconBadgeNumber = count; completion?(nil) }
    }
}
extension String {
    func minisRegularExpressionRanges(_ pattern: String) -> [Range<String.Index>] {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        return regex.matches(in: self, range: NSRange(startIndex..<endIndex, in: self)).compactMap { Range($0.range, in: self) }
    }
}


enum MinisScrollDismissMode { case automatic, immediately, interactively, never }
private struct MinisKeyboardDismissProbe: UIViewRepresentable {
    let mode: MinisScrollDismissMode
    func makeUIView(context: Context) -> UIView { UIView(frame: .zero) }
    func updateUIView(_ view: UIView, context: Context) {
        DispatchQueue.main.async {
            var parent = view.superview
            while let candidate = parent {
                if let scroll = candidate as? UIScrollView {
                    switch mode {
                    case .interactively: scroll.keyboardDismissMode = .interactive
                    case .immediately: scroll.keyboardDismissMode = .onDrag
                    default: scroll.keyboardDismissMode = .none
                    }
                    break
                }
                parent = candidate.superview
            }
        }
    }
}
extension View {
    @ViewBuilder func minisScrollDismissesKeyboard(_ mode: MinisScrollDismissMode) -> some View {
        if #available(iOS 16.0, *) {
            switch mode {
            case .automatic: self.scrollDismissesKeyboard(.automatic)
            case .immediately: self.scrollDismissesKeyboard(.immediately)
            case .interactively: self.scrollDismissesKeyboard(.interactively)
            case .never: self.scrollDismissesKeyboard(.never)
            }
        } else { self.background(MinisKeyboardDismissProbe(mode: mode).frame(width: 0, height: 0)) }
    }
}


enum MinisTextViewFactory {
    static func make(usingTextLayoutManager enabled: Bool) -> UITextView {
        if #available(iOS 16.0, *) { return UITextView(usingTextLayoutManager: enabled) }
        return UITextView(frame: .zero, textContainer: nil)
    }
}
extension HorizontalAlignment {
    static var minisListRowSeparatorLeading: HorizontalAlignment {
        if #available(iOS 16.0, *) { return .listRowSeparatorLeading }
        return .leading
    }
}
extension View {
    @ViewBuilder func minisLineLimit(_ range: ClosedRange<Int>) -> some View {
        if #available(iOS 16.0, *) { self.lineLimit(range) }
        else { self.lineLimit(range.upperBound) }
    }
}

/// Multiline input fallback for iOS 15; preserves editing instead of hiding the field.
struct MinisMultilineTextField: View {
    let title: String
    @Binding var text: String
    init(_ title: String, text: Binding<String>) {
        self.title = title
        self._text = text
    }
    @ViewBuilder var body: some View {
        if #available(iOS 16.0, *) {
            TextField(title, text: $text, axis: .vertical)
        } else {
            ZStack(alignment: .topLeading) {
                if text.isEmpty { Text(title).foregroundColor(.secondary).padding(.top, 8).padding(.leading, 5) }
                TextEditor(text: $text).opacity(text.isEmpty ? 0.75 : 1).frame(minHeight: 70)
            }
        }
    }
}
