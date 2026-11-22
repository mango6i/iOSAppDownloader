package storeauth

import (
	"context"
	"crypto/tls"
	"encoding/base64"
	"errors"
	"net"
	"net/http"
	"os"
	"testing"
	"time"
)

func TestPinnedAppleRootValidAndTampered(t *testing.T) {
	data, err := base64.StdEncoding.DecodeString(appleRootDERBase64)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = parsePinnedAppleRoot(data, time.Now()); err != nil {
		t.Fatal(err)
	}
	if _, err = parsePinnedAppleRoot(data, time.Date(2036, 1, 1, 0, 0, 0, 0, time.UTC)); err == nil {
		t.Fatal("expired root accepted")
	}
	data[20] ^= 1
	if _, err = parsePinnedAppleRoot(data, time.Now()); err == nil {
		t.Fatal("tampered root accepted")
	}
}

func TestAppleRootInstallIsPrivateAndOffline(t *testing.T) {
	calls := 0
	transport := &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12},
		DialContext: func(context.Context, string, string) (net.Conn, error) {
			calls++
			return nil, errors.New("network forbidden")
		}}
	client := &http.Client{Transport: transport}
	if err := installAppleRoot(context.Background(), client); err != nil {
		t.Fatal(err)
	}
	if calls != 0 {
		t.Fatal("root installation requested network")
	}
	if transport.TLSClientConfig.RootCAs != nil {
		t.Fatal("modified original shared transport")
	}
	updated := client.Transport.(*http.Transport)
	if updated.TLSClientConfig.RootCAs == nil || updated.TLSClientConfig.InsecureSkipVerify {
		t.Fatal("TLS verification disabled")
	}
}

func TestAppleProvisioningTLS(t *testing.T) {
	if os.Getenv("IOSAPP_TLS_CHECK") != "1" {
		t.Skip("explicit network check only; no Apple account used")
	}
	client := NewHTTPClient(nil)
	if err := installAppleRoot(context.Background(), client); err != nil {
		t.Fatal(err)
	}
	response, err := client.Get("https://gsa.apple.com/grandslam/MidService/startMachineProvisioning")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	t.Logf("Apple provisioning TLS verified; HTTP %d; no sign-in or account data submitted", response.StatusCode)
}
