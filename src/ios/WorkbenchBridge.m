#import "WorkbenchBridge.h"
#import <objc/message.h>
#include <archive.h>
#include <archive_entry.h>
static id MBGet(id object, NSString *name) {
    SEL s = NSSelectorFromString(name);
    if (!object || ![object respondsToSelector:s]) return nil;
    return ((id (*)(id, SEL))objc_msgSend)(object, s);
}
@implementation MinisDeviceBridge
// Read to memory only: never allow an archive writer to materialize paths,
// links or special files on the phone. Swift applies the package rules next.
+ (NSDictionary<NSString *, NSData *> *)readRAR:(NSData *)data error:(NSError **)error {
    struct archive *reader = archive_read_new();
    NSMutableDictionary *files = [NSMutableDictionary dictionary];
    NSMutableSet *seen = [NSMutableSet set];
    NSString *failure = nil;
    size_t total = 0, entries = 0;
    archive_read_support_filter_none(reader);
    archive_read_support_format_rar(reader);
    archive_read_support_format_rar5(reader);
    if (data.length > 50 * 1024 * 1024 || archive_read_open_memory(reader, data.bytes, data.length) != ARCHIVE_OK) {
        failure = @"RAR 损坏、加密或超过 50 MB";
    } else {
        struct archive_entry *entry;
        int status;
        while ((status = archive_read_next_header(reader, &entry)) != ARCHIVE_EOF) {
            if (status != ARCHIVE_OK) { failure = @"RAR 条目无法解码（可能加密或分卷）"; break; }
            const char *raw = archive_entry_pathname_utf8(entry);
            if (!raw) raw = archive_entry_pathname(entry);
            NSString *name = raw ? [NSString stringWithUTF8String:raw] : nil;
            NSArray *parts = [name componentsSeparatedByString:@"/"];
            if (++entries > 5000 || !name.length || [name hasPrefix:@"/"] ||
                [name containsString:@"\\"] || [name containsString:@":"] ||
                [name rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location != NSNotFound ||
                [parts containsObject:@".."] || [parts containsObject:@"."] ||
                [seen containsObject:name.lowercaseString] || archive_entry_symlink(entry) || archive_entry_hardlink(entry) ||
                archive_entry_is_encrypted(entry) > 0) {
                failure = @"RAR 路径、链接、加密或条目数校验失败"; break;
            }
            [seen addObject:name.lowercaseString];
            if (archive_entry_filetype(entry) == AE_IFDIR) { archive_read_data_skip(reader); continue; }
            if (archive_entry_filetype(entry) != AE_IFREG) { failure = @"RAR 含特殊文件"; break; }
            NSMutableData *body = [NSMutableData data];
            char buffer[32768]; la_ssize_t count;
            while ((count = archive_read_data(reader, buffer, sizeof(buffer))) > 0) {
                total += (size_t)count;
                if (total > 50 * 1024 * 1024) { failure = @"RAR 展开总大小超过 50 MB"; break; }
                [body appendBytes:buffer length:(NSUInteger)count];
            }
            if (count < 0) failure = @"RAR 解压或校验失败";
            if (failure) break;
            files[name] = body;
        }
    }
    archive_read_free(reader);
    if (failure) {
        if (error) *error = [NSError errorWithDomain:@"MinisArchive" code:1 userInfo:@{NSLocalizedDescriptionKey:failure}];
        return nil;
    }
    return files;
}

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
