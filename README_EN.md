# iOS App Downloader

<p align="center">
  <a href="https://mango6i.github.io/iOSAppDownloader/?lang=en"><kbd>English</kbd></a>
  &nbsp;|&nbsp;
  <a href="https://mango6i.github.io/iOSAppDownloader/?lang=zh"><kbd>中文</kbd></a>
</p>

<p>
  <strong><font color="#d00000" size="5">This software is open-source and free. Beware of scams!!!</font></strong><br>
  <strong><font color="#d00000" size="4">This software never collects users' account passwords; the code is public and transparent!!!</font></strong>
</p>

A simple Windows tool for searching App Store apps, viewing older versions, and downloading selected versions as IPA files for installation with tools such as iMazing or 爱思助手.

## Features

- Apple ID sign-in with two-factor authentication code support
- Automatically tries the system proxy, local proxy ports, and direct connection
- The account session is valid only while the app is running; sign-out and exit clear it
- Version History provides “Official version list” and “Login-free lookup” modes
- Download queue supports up to 10 simultaneous tasks
- Each task shows its size, speed, progress, elapsed time, and remaining time
- Open the download folder directly after a task completes
- Language options: Follow system, Simplified Chinese, or English

## Usage

1. Double-click `iOSAppDownloader.exe`.
2. Open Settings and sign in with an Apple ID. If two-factor authentication is enabled, enter the 6-digit code in the verification-code field.
3. Search for an app in App Search and double-click it to open Version History.
4. Choose “Official version list” or “Login-free lookup”, select versions, and add them to the download queue.
5. When a download finishes, click Open in the task row or use the Settings page to open the download folder.

When a region outside Mainland China is selected, the app warns that the Apple ID must have App Store access for that region. Login-free lookup may still show information, but official version retrieval and downloads may not work without a matching regional account.

## Screenshots

The following screenshots show the actual software interface. The account and path shown are public examples and do not contain user privacy.

### App Search

![App Search](images/01-search.png)

### Version History

![Version History](images/02-history.png)

### Download Queue

![Download Queue](images/03-downloads.png)

### Apple ID Settings

![Apple ID Settings](images/04-settings.png)

## Release

This repository includes the Windows release and the project source:

- `iOSAppDownloader.exe`: ready-to-use Windows build
- `ios_old_app_downloader.py`: main source file
- `ios_old_app_downloader.spec`, `version_info.txt`, and `appstore.ico`: packaging files
- `ipatool/`: required ipatool-rs runtime components

Download the EXE for normal use, or inspect the source and rebuild it in your own environment.

### Customizing the language and startup prompt

The Chinese and English UI strings are centralized in the `TRANSLATIONS` dictionary near the top of `ios_old_app_downloader.py`. Edit `startup_login_message()` to change the startup “Sign in first” dialog. Follow system uses the Windows/Qt locale, while a manual language choice takes effect immediately.

## API Source

The Apple ID sign-in, version listing, and IPA download capabilities use the open-source **ipatool** API. The bundled Windows runtime component is provided by [Kosthi/ipatool-rs](https://github.com/Kosthi/ipatool-rs).
