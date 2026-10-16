#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

FOUNDATION_EXPORT void PvZSetInstantKill(BOOL enabled);
FOUNDATION_EXPORT void PvZSetRapidFire(BOOL enabled);
FOUNDATION_EXPORT BOOL PvZInstantKillEnabled(void);
FOUNDATION_EXPORT BOOL PvZRapidFireEnabled(void);
FOUNDATION_EXPORT BOOL PvZBackendReady(void);
FOUNDATION_EXPORT NSString *PvZBackendStatus(void);

NS_ASSUME_NONNULL_END
