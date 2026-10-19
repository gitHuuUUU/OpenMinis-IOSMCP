import Foundation

/// Optional HTTPS import. HEAD rejects known-large bodies before downloading;
/// the actual response and every chunk are bounded too (HEAD is not trusted).
final class ExtensionDownload: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private var bytes = Data()
    private var continuation: CheckedContinuation<Data, Error>?
    private var session: URLSession?
    private var expected: Int64 = 0

    static func fetch(_ url: URL, configuration: URLSessionConfiguration = .ephemeral) async throws -> Data {
        guard url.scheme?.lowercased() == "https", url.host != nil, url.user == nil, url.password == nil else {
            throw ExtensionPackageReader.fail("扩展下载仅支持无内嵌凭据的 HTTPS 地址")
        }
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 120
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        let headSession = URLSession(configuration: configuration)
        defer { headSession.invalidateAndCancel() }
        var request = URLRequest(url: url); request.httpMethod = "HEAD"
        let (_, response) = try await headSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode),
              http.url?.scheme == "https", let header = http.value(forHTTPHeaderField: "Content-Length"),
              let length = Int64(header), (1...Int64(ExtensionPackageReader.maxBytes)).contains(length) else {
            throw ExtensionPackageReader.fail("下载前校验失败：服务器必须提供有效 Content-Length，且 ZIP 不超过 50 MB；可改用文件导入")
        }
        let download = ExtensionDownload()
        return try await withCheckedThrowingContinuation { continuation in
            download.continuation = continuation
            download.session = URLSession(configuration: configuration, delegate: download, delegateQueue: nil)
            download.session?.dataTask(with: url).resume()
        }
    }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse, completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode),
              http.url?.scheme == "https", (1...Int64(ExtensionPackageReader.maxBytes)).contains(response.expectedContentLength) else {
            completionHandler(.cancel); finish(.failure(ExtensionPackageReader.fail("实际下载响应大小未知、超限或不是 HTTPS"))); return
        }
        expected = response.expectedContentLength
        completionHandler(.allow)
    }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        guard bytes.count + data.count <= ExtensionPackageReader.maxBytes else {
            dataTask.cancel(); finish(.failure(ExtensionPackageReader.fail("下载内容超过 50 MB，已中止"))); return
        }
        bytes.append(data)
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error { finish(.failure(error)) }
        else if bytes.count != expected { finish(.failure(ExtensionPackageReader.fail("Content-Length 与下载内容不一致"))) }
        else { finish(.success(bytes)) }
    }
    private func finish(_ result: Result<Data, Error>) {
        guard let pending = continuation else { return }
        continuation = nil
        pending.resume(with: result)
        session?.invalidateAndCancel(); session = nil
    }
}
