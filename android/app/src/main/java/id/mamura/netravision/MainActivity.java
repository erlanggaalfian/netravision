package id.mamura.netravision;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.Context;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/* NetraVision Android: WebView minimal yang memuat situs live.
 * Tanpa dependensi eksternal (tanpa androidx/Capacitor) supaya bisa
 * dibangun dengan aapt2 + d8 saja, tanpa Gradle. */
public class MainActivity extends Activity {
    private static final String HOME_URL = "https://netra.mamura.net.id/";
    private WebView webView;

    /* Versi aplikasi dari manifest (versionName), dipakai untuk memberi
       tahu situs bahwa pengunjung memakai aplikasi (bukan browser) dan
       versi berapa, supaya situs bisa menampilkan tombol update hanya
       bila ada versi baru. */
    private String appVersion() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "1.0.0";
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        /* Latar gelap (#0a0e13, sama dengan tema gelap web) sebagai
           "splash" sebelum halaman web dimuat: tanpa ini latar WebView
           default putih berkilat saat aplikasi dibuka, sebelum skrip
           anti-FOUC tema web sempat jalan. */
        getWindow().getDecorView().setBackgroundColor(0xFF0A0E13);
        webView = new WebView(this);
        webView.setBackgroundColor(0xFF0A0E13);
        setContentView(webView);
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        /* Sisipkan "NetraVision/<versi>" ke User-Agent supaya situs bisa
           membedakan pengunjung aplikasi vs browser dan tahu versi
           terpasang. */
        s.setUserAgentString(s.getUserAgentString() + " NetraVision/" + appVersion());
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false);
        /* Semua navigasi tetap di dalam WebView. */
        webView.setWebViewClient(new WebViewClient());
        /* Unduhan (mis. tautan Download APK) diteruskan ke DownloadManager
           sistem supaya file tersimpan dan bisa dipasang. */
        webView.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent,
                                        String contentDisposition, String mimetype,
                                        long contentLength) {
                DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
                req.setMimeType(mimetype);
                req.addRequestHeader("User-Agent", userAgent);
                req.addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url));
                req.setTitle(Uri.parse(url).getLastPathSegment());
                req.setNotificationVisibility(
                        DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                req.setDestinationInExternalPublicDir(
                        Environment.DIRECTORY_DOWNLOADS,
                        Uri.parse(url).getLastPathSegment());
                ((DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE)).enqueue(req);
            }
        });
        if (savedInstanceState == null) {
            webView.loadUrl(HOME_URL);
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        webView.saveState(outState);
    }

    @Override
    protected void onRestoreInstanceState(Bundle savedInstanceState) {
        super.onRestoreInstanceState(savedInstanceState);
        webView.restoreState(savedInstanceState);
    }

    /* Tombol back Android: mundur di riwayat WebView bila ada, bila tidak
       keluar aplikasi (perilaku standar). */
    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }
}
