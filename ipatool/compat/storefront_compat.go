// Offline baseline from majd/ipatool v2.7.0 (MIT), with 2.8.1 dynamic discovery
// retained for unknown IDs. Account storefront always comes from Apple, not IP
// geolocation, the email address, or the GUI's selected search region.
package appstore

import (
	_ "embed"
	"encoding/json"
	"strings"
)

//go:embed storefronts.json
var bundledStorefronts []byte

func knownStorefrontCountryCodes() map[string]string {
	var byCountry map[string]string
	if err := json.Unmarshal(bundledStorefronts, &byCountry); err != nil {
		panic("invalid bundled storefront mapping")
	}
	result := make(map[string]string, len(byCountry))
	for country, identifier := range byCountry {
		result[identifier] = country
	}
	return result
}

// StorefrontCountryCode is metadata only: it grants no regional account rights.
func StorefrontCountryCode(storefront string) string {
	return knownStorefrontCountryCodes()[storefrontIdentifier(strings.TrimSpace(storefront))]
}
