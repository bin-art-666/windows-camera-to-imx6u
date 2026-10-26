#include <QApplication>
#include <QCommandLineParser>
#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QImageReader>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QNetworkAccessManager>
#include <QNetworkProxy>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QPushButton>
#include <QSaveFile>
#include <QTimer>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QCloseEvent>
#include <QDebug>
#include <QBuffer>
#include <csignal>

static const int MaxJpeg = 4 * 1024 * 1024;
static volatile std::sig_atomic_t stopRequested = 0;
static void requestStop(int) { stopRequested = 1; }

class Viewer : public QWidget {
public:
    Viewer(const QUrl &source, const QString &directory, int interval, int limit,
           const QString &screenshot) : source(source), directory(directory),
        interval(interval), limit(limit), screenshot(screenshot) {
        setWindowTitle(QStringLiteral("Camera Transport — 开发板网络摄像头"));
        resize(1024, 600);
        auto layout = new QVBoxLayout(this);
        auto title = new QLabel(QStringLiteral("电脑摄像头 · 开发板实时预览"));
        title->setStyleSheet("font-size:24px;font-weight:bold;");
        layout->addWidget(title);
        auto bar = new QHBoxLayout;
        address = new QLineEdit(source.toString());
        address->setReadOnly(true);
        auto pause = new QPushButton(QStringLiteral("暂停 / 继续"));
        auto exit = new QPushButton(QStringLiteral("退出并恢复桌面"));
        pause->setMinimumHeight(44); exit->setMinimumHeight(44);
        bar->addWidget(address, 1); bar->addWidget(pause); bar->addWidget(exit);
        layout->addLayout(bar);
        preview = new QLabel(QStringLiteral("正在连接电脑摄像头…"));
        preview->setAlignment(Qt::AlignCenter);
        preview->setMinimumSize(320, 240);
        preview->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Expanding);
        preview->setStyleSheet("background:#15212d;color:#e1eaf4;font-size:22px;");
        layout->addWidget(preview, 1);
        status = new QLabel;
        status->setMinimumHeight(32);
        status->setStyleSheet("font-size:17px;");
        layout->addWidget(status);
        auto note = new QLabel(QStringLiteral("图像来自 Windows 摄像头，经网线传输；断线自动重连。"));
        layout->addWidget(note);
        manager.setProxy(QNetworkProxy::NoProxy);
        deadline.setSingleShot(true);
        poll.setSingleShot(true);
        connect(&deadline, &QTimer::timeout, this, [this] {
            if (reply) { error = "Request timed out"; reply->abort(); }
        });
        connect(&poll, &QTimer::timeout, this, [this] { request(); });
        connect(&watchdog, &QTimer::timeout, this, [this] {
            if (!paused && lastFrame.isValid() && lastFrame.elapsed() > 2500) {
                preview->clear(); preview->setText(QStringLiteral("画面已过期，正在重新连接…"));
                state = "reconnecting";
                status->setText(QStringLiteral("连接中断或无新帧，自动重试；已接收 %1 帧").arg(frames));
                writeMetrics();
            }
        });
        connect(pause, &QPushButton::clicked, this, [this] {
            paused = !paused;
            if (paused) {
                poll.stop();
                if (reply) reply->abort();
                state = "paused";
                preview->clear(); preview->setText(QStringLiteral("预览已暂停"));
                status->setText(QStringLiteral("点击“暂停 / 继续”恢复接收"));
                writeMetrics();
            } else { previous.clear(); lastFrame.invalidate(); request(); }
        });
        connect(exit, &QPushButton::clicked, this, &QWidget::close);
        total.start(); sample.start();
        watchdog.start(500);
        QDir().mkpath(directory);
        QTimer::singleShot(0, this, [this] { request(); });
    }

    void finish() {
        if (closing) return;
        closing = true;
        poll.stop(); watchdog.stop(); deadline.stop();
        if (reply) reply->abort();
        state = "stopped";
        writeMetrics();
        qInfo().noquote() << "STOP frames=" + QString::number(frames)
                           + " errors=" + QString::number(errors);
    }

    int frameCount() const { return frames; }

protected:
    void closeEvent(QCloseEvent *event) override { finish(); event->accept(); }

private:
    QUrl source;
    QString directory;
    int interval, limit;
    QString screenshot;
    QLabel *preview, *status;
    QLineEdit *address;
    QNetworkAccessManager manager;
    QNetworkReply *reply = nullptr;
    QTimer poll, deadline, watchdog;
    QElapsedTimer total, sample, lastFrame;
    QByteArray previous;
    int frames = 0, errors = 0, sampleFrames = 0;
    int width = 0, height = 0;
    double fps = 0;
    bool paused = false, closing = false;
    QString state = "connecting", error;

    bool atomicWrite(const QString &name, const QByteArray &data) {
        QSaveFile file(directory + "/" + name);
        return file.open(QIODevice::WriteOnly) && file.write(data) == data.size() && file.commit();
    }

    void writeMetrics() {
        QJsonObject object;
        object["state"] = state;
        object["frames"] = frames;
        object["errors"] = errors;
        object["width"] = width; object["height"] = height;
        object["fps"] = fps;
        object["source_sequence"] = QString::fromLatin1(previous);
        object["source"] = source.toString();
        object["error"] = error;
        object["elapsed_ms"] = double(total.elapsed());
        object["frame_age_ms"] = lastFrame.isValid() ? double(lastFrame.elapsed()) : -1;
        object["board_time"] = QDateTime::currentDateTime().toString(Qt::ISODate);
        if (!atomicWrite("status.json", QJsonDocument(object).toJson(QJsonDocument::Compact)))
            qWarning() << "Could not write status.json";
    }

    void failure(const QString &message) {
        ++errors; error = message; state = "reconnecting";
        status->setText(QStringLiteral("连接失败，自动重试：%1").arg(message.left(100)));
        qWarning().noquote() << "RETRY" << message;
        writeMetrics();
    }

    void request() {
        if (paused || closing || reply) return;
        QUrl url(source);
        url.setPath(source.path().replace(QRegExp("/$"), "") + "/frame.jpg");
        QNetworkRequest request(url);
        request.setRawHeader("Cache-Control", "no-cache");
        reply = manager.get(request);
        reply->setReadBufferSize(MaxJpeg + 1);
        deadline.start(3000);
        connect(reply, &QNetworkReply::readyRead, this, [this] {
            if (reply && (reply->bytesAvailable() > MaxJpeg ||
                reply->header(QNetworkRequest::ContentLengthHeader).toLongLong() > MaxJpeg)) {
                error = "JPEG exceeds 4 MiB limit"; reply->abort();
            }
        });
        connect(reply, &QNetworkReply::finished, this, [this] {
            deadline.stop();
            QNetworkReply *done = reply;
            reply = nullptr;
            if (!closing && !paused) {
                if (done->error() != QNetworkReply::NoError ||
                    done->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt() != 200) {
                    failure(done->errorString());
                } else {
                    const QByteArray sequence = done->rawHeader("X-Frame-Sequence");
                    const QByteArray data = done->readAll();
                    if (sequence.isEmpty() || sequence != previous) consume(data, sequence);
                }
            }
            done->deleteLater();
            if (!closing && !paused) poll.start(interval);
        });
    }

    void consume(const QByteArray &jpeg, const QByteArray &sequence) {
        if (jpeg.size() > MaxJpeg || !jpeg.startsWith(QByteArray::fromHex("ffd8")) ||
            !jpeg.endsWith(QByteArray::fromHex("ffd9"))) {
            failure("Incomplete or oversized JPEG"); return;
        }
        QBuffer buffer;
        buffer.setData(jpeg); buffer.open(QIODevice::ReadOnly);
        QImageReader reader(&buffer, "JPEG");
        const QSize size = reader.size();
        if (!size.isValid() || size.width() > 1920 || size.height() > 1080) {
            failure("Invalid JPEG dimensions (maximum 1920x1080)"); return;
        }
        const QImage image = reader.read();
        if (image.isNull()) { failure("JPEG decoding failed: " + reader.errorString()); return; }
        if (!atomicWrite("latest.jpg", jpeg)) { failure("Cannot save latest.jpg"); return; }
        previous = sequence;
        ++frames; ++sampleFrames;
        width = image.width(); height = image.height();
        lastFrame.restart();
        if (sample.elapsed() >= 1000) {
            fps = sampleFrames * 1000.0 / sample.elapsed();
            sample.restart(); sampleFrames = 0;
        }
        state = "live"; error.clear();
        preview->setPixmap(QPixmap::fromImage(image).scaled(preview->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
        status->setText(QStringLiteral("正在接收  %1×%2  |  %3 fps  |  %4 帧  |  %5 KB")
                        .arg(width).arg(height).arg(fps, 0, 'f', 1).arg(frames).arg(jpeg.size() / 1024.0, 0, 'f', 1));
        writeMetrics();
        if (frames == 1 || frames % 25 == 0)
            qInfo() << "FRAME" << frames << "size" << image.size() << "fps" << fps;
        if (!screenshot.isEmpty() && frames == 5) {
            const QString path = screenshot;
            QTimer::singleShot(0, this, [this, path] {
                qInfo() << "SCREENSHOT" << grab().save(path);
            });
        }
        if (limit > 0 && frames >= limit)
            QTimer::singleShot(0, qApp, &QApplication::quit);
    }
};

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    std::signal(SIGTERM, requestStop);
    std::signal(SIGINT, requestStop);
    QTimer signalPoll;
    QObject::connect(&signalPoll, &QTimer::timeout, &app, [&app] {
        if (stopRequested) app.quit();
    });
    signalPoll.start(100);
    app.setApplicationName("camera_viewer_arm");
    QCommandLineParser parser;
    parser.addHelpOption();
    parser.addOption({"server", "Windows camera HTTP URL", "url", "http://192.168.1.100:8080"});
    parser.addOption({"output", "Latest JPEG and status directory", "directory", "/tmp/camera_transport"});
    parser.addOption({"fps", "Maximum request rate (1..20)", "fps", "5"});
    parser.addOption({"max-frames", "Quit after N valid frames, 0 means continuous", "count", "0"});
    parser.addOption({"exit-after", "Quit after N seconds, 0 means continuous", "seconds", "0"});
    parser.addOption({"screenshot", "Save application screenshot after 5 frames", "path"});
    parser.process(app);
    const QUrl server(parser.value("server"));
    bool validFps, validFrames, validSeconds;
    const int fps = parser.value("fps").toInt(&validFps);
    const int frames = parser.value("max-frames").toInt(&validFrames);
    const int seconds = parser.value("exit-after").toInt(&validSeconds);
    if (server.scheme() != "http" || server.host().isEmpty() || !server.query().isEmpty() ||
        !validFps || fps < 1 || fps > 20 || !validFrames || frames < 0 ||
        !validSeconds || seconds < 0 || seconds > 86400) {
        qCritical() << "Invalid arguments"; return 2;
    }
    if (!QImageReader::supportedImageFormats().contains("jpeg")) {
        qCritical() << "JPEG plugin unavailable"; return 3;
    }
    Viewer viewer(server, parser.value("output"), 1000 / fps, frames, parser.value("screenshot"));
    QObject::connect(&app, &QApplication::aboutToQuit, &viewer, [&viewer] { viewer.finish(); });
    viewer.showFullScreen();
    if (seconds > 0) QTimer::singleShot(seconds * 1000, &app, &QApplication::quit);
    const int result = app.exec();
    return result ? result : ((frames > 0 && viewer.frameCount() < frames) ? 4 : 0);
}
