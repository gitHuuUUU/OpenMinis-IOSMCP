#import "WorkbenchBridge.h"
#import <objc/message.h>
static id MBGet(id object, NSString *name) {
    SEL s = NSSelectorFromString(name);
    if (!object || ![object respondsToSelector:s]) return nil;
    return ((id (*)(id, SEL))objc_msgSend)(object, s);
}
@implementation MinisDeviceBridge
+ (NSArray *)applications {
    @try {
        id workspace = MBGet(NSClassFromString(@"LSApplicationWorkspace"), @"defaultWorkspace");
        id proxies = MBGet(workspace, @"allInstalledApplications");
        if (![proxies isKindOfClass:NSArray.class]) return @[];
        NSMutableArray *result = [NSMutableArray array];
        for (id proxy in proxies) {
            id bid = MBGet(proxy, @"bundleIdentifier");
            if (![bid isKindOfClass:NSString.class]) continue;
            id name = MBGet(proxy, @"localizedName");
            id bundle = MBGet(proxy, @"bundleURL");
            id data = MBGet(proxy, @"dataContainerURL");
            [result addObject:@{@"bundleID":bid, @"name":[name isKindOfClass:NSString.class]?name:bid,
                @"bundlePath":[bundle isKindOfClass:NSURL.class]?[bundle path]:@"",
                @"dataPath":[data isKindOfClass:NSURL.class]?[data path]:@""}];
        }
        return result;
    } @catch (NSException *e) { return @[]; }
}
+ (BOOL)openApplication:(NSString *)bundleID {
    @try {
        id workspace = MBGet(NSClassFromString(@"LSApplicationWorkspace"), @"defaultWorkspace");
        SEL sel = NSSelectorFromString(@"openApplicationWithBundleID:");
        return [workspace respondsToSelector:sel] && ((BOOL (*)(id,SEL,id))objc_msgSend)(workspace,sel,bundleID);
    } @catch (NSException *e) { return NO; }
}
@end
