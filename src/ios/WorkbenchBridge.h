#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
@interface MinisDeviceBridge : NSObject
+ (NSArray<NSDictionary<NSString *, NSString *> *> *)applications;
+ (nullable NSDictionary<NSString *, NSData *> *)readRAR:(NSData *)data error:(NSError **)error;
+ (BOOL)openApplication:(NSString *)bundleID;
@end
NS_ASSUME_NONNULL_END
