"""TypedDicts mirroring the raw JSON shapes returned by api.ovpay.nl."""

from __future__ import annotations

from typing import NotRequired, TypedDict


# GET /api/v1/TransitAccounts → list[TransitAccountData]
# Sample:
# {
#   "xtat": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
#   "xbot": "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy",
#   "arlStatus": null, "mediumType": "PhysicalEmvClt", "status": "Active",
#   "personalization": {"order": 1, "name": "Mijn OV-pas", "color": "Pink", "medium": null},
#   "balance": 690, "cardNumber": "XXXXXXX", "cardSequenceNumber": "XXXX",
#   "expirationDate": "2031-03-31T23:59:00+02:00",
#   "personalAccountData": {"isAvailable": false, "isTagged": false},
#   "hasOpenTrip": false, "hasFullPostPaid": false, "debtTrips": []
# }
class PersonalizationData(TypedDict):
    order: int
    name: str
    color: str
    medium: str | None


class PersonalAccountDataDict(TypedDict):
    isAvailable: bool
    isTagged: bool


class TransitAccountData(TypedDict):
    xtat: NotRequired[str]  # absent in the `token` field of TripDetailsData
    xbot: str
    status: str
    mediumType: str
    arlStatus: str | None
    tokenOnDenyListForBadDebt: None  # always null in observed responses
    debtPaymentTerm: None  # always null in observed responses
    debt: None  # always null in observed responses
    isProvisional: bool | None
    provisionalFinalTravelDate: str | None
    personalization: PersonalizationData
    balance: int | None
    traveledToday: None  # always null in observed responses
    cardNumber: str | None
    cardSequenceNumber: str | None
    expirationDate: str | None
    personalAccountData: PersonalAccountDataDict
    hasOpenTrip: bool
    hasFullPostPaid: bool
    securityState: None  # always null in observed responses
    debtTrips: list[object]


# GET /api/v3/Trips/{xtat}?offset=0 → TripsPageData
# GET /api/v3/Trips/{xbot}/{trip_id} → TripDetailsData
# Sample trip object:
# {
#   "xbot": "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy",
#   "id": 123456789, "version": 1, "transport": "BUS", "status": "CheckedOut",
#   "checkInLocation": "Street Name",
#   "checkInTimestamp": "2026-06-24T13:14:00+02:00",
#   "checkOutLocation": "Another Street",
#   "checkOutTimestamp": "2026-06-24T13:30:00+02:00",
#   "currency": "EUR", "fare": 87, "organisationName": "GVB",
#   "fareNature": "Fare", "paymentMethodName": "EPURSE",
#   "salesProductCommercialName": "..."
# }
class TripData(TypedDict):
    xbot: str
    id: int
    version: int
    transport: str
    status: str
    checkInLocation: NotRequired[str | None]
    checkInTimestamp: NotRequired[str | None]
    checkOutLocation: NotRequired[str | None]
    checkOutTimestamp: NotRequired[str | None]
    currency: str | None
    fare: int | None
    organisationName: str | None
    loyaltyOrDiscount: NotRequired[bool | None]
    fareNature: str | None
    paymentMethodName: str | None
    salesProductCommercialName: str | None


# One item in GET /api/v3/Trips/{xtat}?offset=0 → items[]
# Sample keys: trip, correctedFrom, correctedFromType, supersedesFare,
#              ageDiscounts, productDiscounts, dayCapping,
#              icDirectSupplement, postPaidPaymentInformation
# All correction/discount fields are null in standard (non-corrected) trips.
class TripItemData(TypedDict):
    trip: TripData
    correctedFrom: None
    correctedFromType: None
    supersedesFare: None
    ageDiscounts: list[object]
    productDiscounts: list[object]
    dayCapping: None
    icDirectSupplement: NotRequired[None]
    postPaidPaymentInformation: None


# GET /api/v3/Trips/{xtat}?offset=0
# Sample: {"offset": 20, "batchSize": 0, "endOfListReached": false, "items": [...]}
class TripsPageData(TypedDict):
    offset: int
    batchSize: int
    endOfListReached: bool
    items: list[TripItemData]


# GET /api/v3/Trips/{xbot}/{trip_id}
# Sample top-level keys: token, correctionOptions, trip, correctedFrom,
#   correctedFromType, supersedesFare, ageDiscounts, productDiscounts,
#   dayCapping, icDirectSupplement, postPaidPaymentInformation
# `token` is a partial TransitAccountData (has xbot but NOT xtat)
class TripDetailsData(TypedDict):
    token: TransitAccountData
    correctionOptions: None
    trip: TripData
    correctedFrom: None
    correctedFromType: None
    supersedesFare: None
    ageDiscounts: list[object]
    productDiscounts: list[object]
    dayCapping: None
    icDirectSupplement: NotRequired[None]
    postPaidPaymentInformation: None


# GET /api/v1/Payments/{xtat}?offset=0 → PaymentsPageData
# Sample payment item:
# {
#   "serviceReferenceId": "XXXXXXXXXXX",
#   "xbot": "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy",
#   "id": "EVENT-O17-XXXXXXXXXXXXXXXXXXXXXXXXXXXX",
#   "status": "Ok", "transactionTimestamp": "2026-06-24T13:30:27+02:00",
#   "transactionType": "Trip", "amount": -87, "amountDue": -87,
#   "currency": "EUR", "paymentMethod": "EPURSE",
#   "rejectionReason": null, "loyaltyOrDiscount": false
# }
class PaymentData(TypedDict):
    serviceReferenceId: str
    xbot: str
    id: str
    status: str
    transactionTimestamp: str
    transactionType: str
    amount: int  # euro-cents, negative = debit
    amountDue: int  # euro-cents, negative = debit
    currency: str
    paymentMethod: str
    rejectionReason: str | None
    loyaltyOrDiscount: bool


# GET /api/v1/Payments/{xtat}?offset=0
# Sample: {"offset": 20, "batchSize": 0, "endOfListReached": false, "items": [...]}
class PaymentsPageData(TypedDict):
    offset: int
    batchSize: int
    endOfListReached: bool
    items: list[PaymentData]


# GET /api/v1/Payments/receipt/{xbot}/{payment_id}
# Sample: {"relatedPayments": [<PaymentData>, ...]}
# payment_id is the EVENT-... string from PaymentData.id (not a trip id)
class PaymentReceiptData(TypedDict):
    relatedPayments: list[PaymentData]


# GET /api/v1/PassengerAccounts
# Sample: {"email": "user@example.com"}
class PassengerAccountData(TypedDict):
    email: str


# GET /api/v1/WebConfig
# Sample feature: {"key": "TopUpBalanceEnabled", "enabled": true}
# Full list has ~98 feature flags covering UI features, card operations,
# payment methods, age discounts, etc.
class WebConfigFeature(TypedDict):
    key: str
    enabled: bool


class WebConfigData(TypedDict):
    features: list[WebConfigFeature]
    documentUpdates: list[object]


# GET /api/v1/Customers
# Sample: {"initials": null, "prefix": null, "lastName": null,
#          "email": "user@example.com", "birthDate": null,
#          "phoneNumber": null, "address": null, "arlContracts": null}
class CustomerAddressData(TypedDict):
    street: NotRequired[str | None]
    houseNumber: NotRequired[str | None]
    houseNumberAddition: NotRequired[str | None]
    postalCode: NotRequired[str | None]
    city: NotRequired[str | None]
    country: NotRequired[str | None]


class CustomerData(TypedDict):
    initials: str | None
    prefix: str | None
    lastName: str | None
    email: str | None
    birthDate: str | None
    phoneNumber: str | None
    address: CustomerAddressData | None
    arlContracts: list[object] | None


# GET /api/v1/LookupAddress?postalCode=<code>&houseNumber=<nr>
class AddressData(TypedDict):
    street: NotRequired[str | None]
    houseNumber: NotRequired[str | None]
    houseNumberAddition: NotRequired[str | None]
    postalCode: NotRequired[str | None]
    city: NotRequired[str | None]
    country: NotRequired[str | None]


# GET /api/Version
class ApiVersionData(TypedDict):
    major: int
    minor: int
    patch: int
    preReleaseTag: str


# GET /api/anonymous/V2/Config
# Same shape as WebConfigData but different feature keys and documentUpdateKeys.
class AnonymousConfigData(TypedDict):
    features: list[WebConfigFeature]
    documentUpdateKeys: dict[str, str]


# GET /api/anonymous/v1/faq/topics → list[FaqTopicData]
class FaqTopicData(TypedDict):
    id: str
    name: str


# GET /api/anonymous/v1/faq/articles?topicId=<id>
class FaqArticleData(TypedDict):
    id: str
    title: str
    topicId: NotRequired[str]
    content: NotRequired[str]


class FaqArticlesPageData(TypedDict):
    offset: int
    batchSize: int
    endOfListReached: bool
    items: list[FaqArticleData]


# GET /api/anonymous/v1/Search?q=<query>
class SearchResultData(TypedDict):
    title: NotRequired[str]
    url: NotRequired[str]
    description: NotRequired[str]


class SearchResponseData(TypedDict):
    searchResults: list[SearchResultData]


class SearchSuggestionsData(TypedDict):
    searchResults: list[SearchResultData]
    articles: list[dict[str, object]]


class CardProductsData(TypedDict):
    products: list[dict[str, object]]
    ageDiscountProfile: dict[str, object] | None


class OvPasPriceData(TypedDict):
    tokenPrice: int
    fullTokenPrice: int
    tokenPriceInEuros: int | float
    voucherStatus: str | None
    voucherDiscountAmount: int | None
    voucherDiscountType: str | None


# GET /api/v2/TripExport/trips?xtat=<xtat>&from=<iso>&to=<iso>
TripExportPageData = TripsPageData


# GET https://www.ovpay.nl/api/auth/session (NextAuth, not api.ovpay.nl)
# Sample: {
#   "user": {"name": "user@example.com", "email": "user@example.com"},
#   "expires": "2026-07-24T12:16:11.491Z",
#   "token": "eyJhbGciOiJSUzI1NiIs...",   ← Keycloak RS256 access token (~1h)
#   "id_token": "eyJhbGciOiJSUzI1NiIs...",
#   "provider": "idp"
# }
class SessionData(TypedDict):
    user: NotRequired[dict[str, str]]
    expires: NotRequired[str]  # iso
    token: NotRequired[str]
    id_token: NotRequired[str]
    provider: NotRequired[str]
    accessToken: NotRequired[str]
    error: NotRequired[str]
