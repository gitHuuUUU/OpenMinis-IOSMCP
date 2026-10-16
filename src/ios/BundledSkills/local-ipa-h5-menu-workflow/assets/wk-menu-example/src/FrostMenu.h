#import <UIKit/UIKit.h>

NS_ASSUME_NONNULL_BEGIN

/// The injected library attaches this menu to the application's existing window.
FOUNDATION_EXPORT UIView *FrostCreateFloatingMenu(void);
FOUNDATION_EXPORT void FrostApplyTheme(UIView *menu, CGFloat red, CGFloat green, CGFloat blue, CGFloat alpha);
FOUNDATION_EXPORT void FrostSetPanelOpacity(UIView *menu, CGFloat opacity);
FOUNDATION_EXPORT NSString *FrostMenuVersion(void);

NS_ASSUME_NONNULL_END
