package appstore

import (
	"errors"
	"io"
	"net/http"
	"testing"

	storehttp "github.com/majd/ipatool/v2/pkg/http"
)

type offlineStorefrontClient struct{ calls int }

func (c *offlineStorefrontClient) Send(storehttp.Request) (storehttp.Result[[]byte], error) {
	c.calls++
	return storehttp.Result[[]byte]{}, errors.New("available storefronts is offline")
}
func (c *offlineStorefrontClient) Do(*http.Request) (*http.Response, error) {
	c.calls++
	return nil, errors.New("network forbidden")
}
func (c *offlineStorefrontClient) NewRequest(string, string, io.Reader) (*http.Request, error) {
	c.calls++
	return nil, errors.New("network forbidden")
}

func TestKnownStorefrontsWorkOffline(t *testing.T) {
	client := &offlineStorefrontClient{}
	store := &appstore{storefrontClient: client, storefrontCountryCodes: knownStorefrontCountryCodes()}
	for id, expected := range map[string]string{"143441": "US", "143465-19,29": "CN", "143463,34": "HK", "143462": "JP", "143470": "TW", "143515": "MO"} {
		country, err := store.countryCodeFromStoreFront(id)
		if err != nil || country != expected {
			t.Fatalf("%s => %s, %v", id, country, err)
		}
	}
	for country, expected := range map[string]string{"US": "143441", "CN": "143465", "JP": "143462"} {
		id, err := store.discoverStorefrontID(country)
		if err != nil || id != expected {
			t.Fatalf("%s => %s, %v", country, id, err)
		}
	}
	if client.calls != 0 {
		t.Fatal("known region depended on online discovery")
	}
}

func TestProductionStorefrontSeedAndUnknownRegion(t *testing.T) {
	store := NewAppStore(Args{}).(*appstore)
	if store.storefrontCountryCodes["143465"] != "CN" {
		t.Fatal("production client has no offline seed")
	}
	if StorefrontCountryCode("999999") != "" {
		t.Fatal("unknown account region was guessed")
	}
	if StorefrontCountryCode("143441-1,34") != "US" {
		t.Fatal("storefront suffix not normalized")
	}
}
