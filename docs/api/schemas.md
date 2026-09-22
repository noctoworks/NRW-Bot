# Схемы данных

Все структуры, используемые в запросах и ответах. Сгенерировано из OpenAPI-схемы (`docs/api/openapi.json`). Деньги — в копейках, если в имени поля `kopeks`; даты — ISO-8601 (UTC).

## Содержание

- [ActiveSubsByTariffOut](#schema-activesubsbytariffout)
- [AdminSubscriptionListItem](#schema-adminsubscriptionlistitem)
- [AdminSubscriptionOut](#schema-adminsubscriptionout)
- [AdminTransactionDetailResponse](#schema-admintransactiondetailresponse)
- [AdminTransactionListItem](#schema-admintransactionlistitem)
- [AdminTransactionOut](#schema-admintransactionout)
- [AdminUserDetailResponse](#schema-adminuserdetailresponse)
- [AdminUserListItem](#schema-adminuserlistitem)
- [AdminUserListResponse](#schema-adminuserlistresponse)
- [AlertOut](#schema-alertout)
- [AuthRequest](#schema-authrequest)
- [AuthResponse](#schema-authresponse)
- [BalanceAdjustRequest](#schema-balanceadjustrequest)
- [BlockRequest](#schema-blockrequest)
- [BroadcastButtonOut](#schema-broadcastbuttonout)
- [BroadcastCreateRequest](#schema-broadcastcreaterequest)
- [BroadcastListResponse](#schema-broadcastlistresponse)
- [BroadcastOptionsResponse](#schema-broadcastoptionsresponse)
- [BroadcastOut](#schema-broadcastout)
- [BroadcastPreviewRequest](#schema-broadcastpreviewrequest)
- [BroadcastPreviewResponse](#schema-broadcastpreviewresponse)
- [BroadcastTargetOut](#schema-broadcasttargetout)
- [BroadcastTariffOut](#schema-broadcasttariffout)
- [CampaignCreateRequest](#schema-campaigncreaterequest)
- [CampaignOut](#schema-campaignout)
- [CampaignStatsResponse](#schema-campaignstatsresponse)
- [CampaignUpdateRequest](#schema-campaignupdaterequest)
- [CohortOut](#schema-cohortout)
- [CohortsResponse](#schema-cohortsresponse)
- [ConnectAppOut](#schema-connectappout)
- [ConnectAppsResponse](#schema-connectappsresponse)
- [ConnectBlockOut](#schema-connectblockout)
- [ConnectButtonOut](#schema-connectbuttonout)
- [ConnectPlatformOut](#schema-connectplatformout)
- [DashboardResponse](#schema-dashboardresponse)
- [DeviceOut](#schema-deviceout)
- [EmojiOut](#schema-emojiout)
- [GiftPurchaseRequest](#schema-giftpurchaserequest)
- [GiftPurchaseResponse](#schema-giftpurchaseresponse)
- [HTTPValidationError](#schema-httpvalidationerror)
- [InfraBillingNodeOut](#schema-infrabillingnodeout)
- [InfraBillingOut](#schema-infrabillingout)
- [LanguageRequest](#schema-languagerequest)
- [LanguageResponse](#schema-languageresponse)
- [LtvResponse](#schema-ltvresponse)
- [MassbanRequest](#schema-massbanrequest)
- [MassbanResponse](#schema-massbanresponse)
- [MessageRequest](#schema-messagerequest)
- [MonitoringResponse](#schema-monitoringresponse)
- [NetProfitOut](#schema-netprofitout)
- [NodeDetailOut](#schema-nodedetailout)
- [NodeMetricOut](#schema-nodemetricout)
- [NodeMetricStat](#schema-nodemetricstat)
- [NodeOut](#schema-nodeout)
- [NodeVersionsOut](#schema-nodeversionsout)
- [OverviewResponse](#schema-overviewresponse)
- [PanelStatsOut](#schema-panelstatsout)
- [PaymentMethodOut](#schema-paymentmethodout)
- [PeriodOut](#schema-periodout)
- [PreviewRequest](#schema-previewrequest)
- [PreviewResponse](#schema-previewresponse)
- [ProfileResponse](#schema-profileresponse)
- [PromoCodeCreateRequest](#schema-promocodecreaterequest)
- [PromoCodeOut](#schema-promocodeout)
- [PromoCodeRequest](#schema-promocoderequest)
- [PromoCodeResponse](#schema-promocoderesponse)
- [PromoCodeUpdateRequest](#schema-promocodeupdaterequest)
- [PromoGroupCreateRequest](#schema-promogroupcreaterequest)
- [PromoGroupOut](#schema-promogroupout)
- [PromoGroupUpdateRequest](#schema-promogroupupdaterequest)
- [PurchaseRequest](#schema-purchaserequest)
- [PurchaseResponse](#schema-purchaseresponse)
- [RecentPaymentOut](#schema-recentpaymentout)
- [ReferralCommissionRequest](#schema-referralcommissionrequest)
- [ReferralFunnelResponse](#schema-referralfunnelresponse)
- [ReferralResponse](#schema-referralresponse)
- [RevenueByProviderDayOut](#schema-revenuebyproviderdayout)
- [RevenueByProviderOut](#schema-revenuebyproviderout)
- [RevenueByTypeOut](#schema-revenuebytypeout)
- [RevenueByWeekdayOut](#schema-revenuebyweekdayout)
- [RevenueCompositionResponse](#schema-revenuecompositionresponse)
- [RevenuePointOut](#schema-revenuepointout)
- [SalesBreakdownResponse](#schema-salesbreakdownresponse)
- [SetUserPromoGroupRequest](#schema-setuserpromogrouprequest)
- [SubscriptionDaysAdjustRequest](#schema-subscriptiondaysadjustrequest)
- [SubscriptionListResponse](#schema-subscriptionlistresponse)
- [SubscriptionOut](#schema-subscriptionout)
- [SubscriptionPulseOut](#schema-subscriptionpulseout)
- [SupportMessageOut](#schema-supportmessageout)
- [SupportReplyRequest](#schema-supportreplyrequest)
- [SupportThreadDetailResponse](#schema-supportthreaddetailresponse)
- [SupportThreadOut](#schema-supportthreadout)
- [SyncResultResponse](#schema-syncresultresponse)
- [TariffChangePreviewResponse](#schema-tariffchangepreviewresponse)
- [TariffChangeRequest](#schema-tariffchangerequest)
- [TariffResponse](#schema-tariffresponse)
- [TariffsResponse](#schema-tariffsresponse)
- [TemplateOut](#schema-templateout)
- [TemplateUpdateRequest](#schema-templateupdaterequest)
- [TopPayerOut](#schema-toppayerout)
- [TopReferrerOut](#schema-topreferrerout)
- [TransactionListResponse](#schema-transactionlistresponse)
- [TransactionOut](#schema-transactionout)
- [UserNodeTrafficOut](#schema-usernodetrafficout)
- [ValidationError](#schema-validationerror)
- [VariableDocOut](#schema-variabledocout)
- [app__cabinet__admin_schemas__PaginatedTransactionsResponse](#schema-app-cabinet-admin-schemas-paginatedtransactionsresponse)
- [app__cabinet__schemas__PaginatedTransactionsResponse](#schema-app-cabinet-schemas-paginatedtransactionsresponse)

## ActiveSubsByTariffOut
<a id="schema-activesubsbytariffout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `tariff_name` | string | да |  |
| `active_count` | integer | да |  |

## AdminSubscriptionListItem
<a id="schema-adminsubscriptionlistitem"></a>

Подписки по ВСЕМ пользователям (см. диалог 2026-09-01) — раньше видна
была только внутри карточки одного юзера (AdminUserDetailResponse.
subscription). Только наши данные (Subscription/Tariff), без обращений
к Remnawave — traffic_used_gb уже синхронизирован фоновой задачей (см.
analytics_service.get_overview::total_traffic_gb).

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `user_id` | integer | да |  |
| `telegram_id` | integer | да |  |
| `username` | string \| null | да |  |
| `full_name` | string \| null | да |  |
| `tariff_name` | string | да |  |
| `status` | string | да |  |
| `is_trial` | boolean | да |  |
| `end_date` | string (date-time) | да |  |
| `traffic_used_gb` | number | да |  |
| `traffic_limit_gb` | integer | да |  |
| `device_limit` | integer | да |  |
| `autopay_enabled` | boolean | да |  |

## AdminSubscriptionOut
<a id="schema-adminsubscriptionout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `status` | string | да |  |
| `end_date` | string (date-time) | да |  |
| `traffic_limit_gb` | integer | да |  |
| `traffic_used_gb` | number | да |  |
| `device_limit` | integer | да |  |
| `is_trial` | boolean | да |  |

## AdminTransactionDetailResponse
<a id="schema-admintransactiondetailresponse"></a>

«Тело транзакции» (см. диалог 2026-09-01, клик по строке в /transactions)
— то же, что в списке, плюс всё, что знаем про сам платёж: статус на нашей
стороне, служебный контекст провижининга (raw_payload) и последний сырой
ответ провайдера (provider_raw_response, см. Payment в models.py) — то,
ради чего изначально заводили это поле при сверке с Platega. Оба None,
если у транзакции вообще нет Payment (топап админом/реферальный бонус).

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | integer | да |  |
| `type` | string | да |  |
| `amount_kopeks` | integer | да |  |
| `status` | string | да |  |
| `description` | string \| null | да |  |
| `created_at` | string (date-time) | да |  |
| `user_id` | integer | да |  |
| `telegram_id` | integer | да |  |
| `username` | string \| null | да |  |
| `full_name` | string \| null | да |  |
| `payment_provider` | string \| null | да |  |
| `payment_external_id` | string \| null | да |  |
| `payment_status` | string \| null | да |  |
| `payment_raw_payload` | object \| null | да |  |
| `provider_raw_response` | object \| null | да |  |

## AdminTransactionListItem
<a id="schema-admintransactionlistitem"></a>

То же, что AdminTransactionOut, плюс кто платил — единый список
/transactions (см. диалог 2026-09-01, "решить вопрос по транзакциям")
показывает транзакции ПО ВСЕМ пользователям, не внутри одной карточки,
поэтому нужна личность плательщика в каждой строке.

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | integer | да |  |
| `type` | string | да |  |
| `amount_kopeks` | integer | да |  |
| `status` | string | да |  |
| `description` | string \| null | да |  |
| `created_at` | string (date-time) | да |  |
| `user_id` | integer | да |  |
| `telegram_id` | integer | да |  |
| `username` | string \| null | да |  |
| `full_name` | string \| null | да |  |
| `payment_provider` | string \| null | да |  |
| `payment_external_id` | string \| null | да |  |

## AdminTransactionOut
<a id="schema-admintransactionout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | integer | да |  |
| `type` | string | да |  |
| `amount_kopeks` | integer | да |  |
| `status` | string | да |  |
| `description` | string \| null | да |  |
| `created_at` | string (date-time) | да |  |

## AdminUserDetailResponse
<a id="schema-adminuserdetailresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | integer | да |  |
| `telegram_id` | integer | да |  |
| `username` | string \| null | да |  |
| `full_name` | string \| null | да |  |
| `language` | string | да |  |
| `is_blocked` | boolean | да |  |
| `blocked_bot` | boolean | да |  |
| `balance_kopeks` | integer | да |  |
| `created_at` | string (date-time) | да |  |
| `last_activity_at` | string (date-time) \| null | да |  |
| `subscription` | [AdminSubscriptionOut](#schema-adminsubscriptionout) \| null | да |  |
| `transactions` | [AdminTransactionOut](#schema-admintransactionout)[] | да |  |
| `referrals_invited_count` | integer | да |  |
| `referrals_earned_kopeks` | integer | да |  |
| `referral_commission_percent` | integer \| null | да |  |
| `promo_group_id` | integer \| null | да |  |
| `promo_group_name` | string \| null | да |  |

## AdminUserListItem
<a id="schema-adminuserlistitem"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | integer | да |  |
| `telegram_id` | integer | да |  |
| `username` | string \| null | да |  |
| `full_name` | string \| null | да |  |
| `is_blocked` | boolean | да |  |
| `has_active_subscription` | boolean | да |  |
| `is_trial` | boolean | да |  |
| `last_activity_at` | string (date-time) \| null | да |  |
| `created_at` | string (date-time) | да |  |

## AdminUserListResponse
<a id="schema-adminuserlistresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `items` | [AdminUserListItem](#schema-adminuserlistitem)[] | да |  |
| `total` | integer | да |  |
| `page` | integer | да |  |
| `total_pages` | integer | да |  |

## AlertOut
<a id="schema-alertout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | string | да |  |
| `severity` | enum: `critical` \| `warning` \| `info` | да |  |
| `title` | string | да |  |
| `link` | string \| null | нет |  |

## AuthRequest
<a id="schema-authrequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `init_data` | string | да |  |

## AuthResponse
<a id="schema-authresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `access_token` | string | да |  |

## BalanceAdjustRequest
<a id="schema-balanceadjustrequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `amount_rub` | number | да |  |

## BlockRequest
<a id="schema-blockrequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `blocked` | boolean | да |  |

## BroadcastButtonOut
<a id="schema-broadcastbuttonout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `key` | string | да |  |
| `label` | string | да |  |

## BroadcastCreateRequest
<a id="schema-broadcastcreaterequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `target` | string | да |  |
| `text` | string | да | длина ≥ 1, длина ≤ 4000 |
| `media_type` | string \| null | нет |  |
| `media_file_id` | string \| null | нет |  |
| `buttons` | string[] | нет |  |

## BroadcastListResponse
<a id="schema-broadcastlistresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `items` | [BroadcastOut](#schema-broadcastout)[] | да |  |
| `total` | integer | да |  |
| `page` | integer | да |  |
| `total_pages` | integer | да |  |

## BroadcastOptionsResponse
<a id="schema-broadcastoptionsresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `targets` | [BroadcastTargetOut](#schema-broadcasttargetout)[] | да |  |
| `tariffs` | [BroadcastTariffOut](#schema-broadcasttariffout)[] | да |  |
| `buttons` | [BroadcastButtonOut](#schema-broadcastbuttonout)[] | да |  |

## BroadcastOut
<a id="schema-broadcastout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | integer | да |  |
| `status` | string | да |  |
| `target_type` | string | да |  |
| `target_display_name` | string | да |  |
| `total_count` | integer | да |  |
| `sent_count` | integer | да |  |
| `failed_count` | integer | да |  |
| `blocked_count` | integer | да |  |
| `has_media` | boolean | да |  |
| `media_type` | string \| null | да |  |
| `admin_name` | string \| null | да |  |
| `created_at` | string (date-time) | да |  |
| `completed_at` | string (date-time) \| null | да |  |

## BroadcastPreviewRequest
<a id="schema-broadcastpreviewrequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `target` | string | да |  |

## BroadcastPreviewResponse
<a id="schema-broadcastpreviewresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `target_display_name` | string | да |  |
| `recipient_count` | integer | да |  |

## BroadcastTargetOut
<a id="schema-broadcasttargetout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `key` | string | да |  |
| `label` | string | да |  |
| `recipient_count` | integer | да |  |

## BroadcastTariffOut
<a id="schema-broadcasttariffout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | integer | да |  |
| `name` | string | да |  |
| `recipient_count` | integer | да |  |

## CampaignCreateRequest
<a id="schema-campaigncreaterequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `name` | string | да | длина ≥ 1, длина ≤ 128 |
| `start_parameter` | string | да | длина ≥ 1, длина ≤ 64 |
| `bonus_type` | string | да |  |
| `balance_bonus_kopeks` | integer | нет | ≥ 0.0, по умолчанию `0` |
| `subscription_duration_days` | integer \| null | нет |  |

## CampaignOut
<a id="schema-campaignout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | integer | да |  |
| `name` | string | да |  |
| `start_parameter` | string | да |  |
| `bonus_type` | string | да |  |
| `balance_bonus_kopeks` | integer | да |  |
| `subscription_duration_days` | integer \| null | да |  |
| `is_active` | boolean | да |  |
| `deep_link` | string | да |  |

## CampaignStatsResponse
<a id="schema-campaignstatsresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `registrations_count` | integer | да |  |
| `paying_count` | integer | да |  |
| `conversion_percent` | number | да |  |
| `revenue_kopeks` | integer | да |  |

## CampaignUpdateRequest
<a id="schema-campaignupdaterequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `name` | string \| null | нет |  |
| `is_active` | boolean \| null | нет |  |
| `balance_bonus_kopeks` | integer \| null | нет |  |
| `subscription_duration_days` | integer \| null | нет |  |

## CohortOut
<a id="schema-cohortout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `cohort_month` | string | да |  |
| `users_count` | integer | да |  |
| `revenue_per_user_by_month_offset` | integer[] | да |  |

## CohortsResponse
<a id="schema-cohortsresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `max_months` | integer | да |  |
| `cohorts` | [CohortOut](#schema-cohortout)[] | да |  |

## ConnectAppOut
<a id="schema-connectappout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | string | да |  |
| `name` | string | да |  |
| `featured` | boolean | да |  |
| `blocks` | [ConnectBlockOut](#schema-connectblockout)[] | да |  |

## ConnectAppsResponse
<a id="schema-connectappsresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `platforms` | [ConnectPlatformOut](#schema-connectplatformout)[] | да |  |

## ConnectBlockOut
<a id="schema-connectblockout"></a>

Один шаг инструкции ("Установка приложения", "Предупреждение", ...) —
рендерится как шаг вертикального таймлайна, см. app/external/remnawave/base.py.

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `title` | string | да |  |
| `description` | string | да |  |
| `icon_key` | string | да |  |
| `icon_color` | string | да |  |
| `buttons` | [ConnectButtonOut](#schema-connectbuttonout)[] | да |  |

## ConnectButtonOut
<a id="schema-connectbuttonout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `type` | string | да |  |
| `label` | string | да |  |
| `url` | string | да |  |

## ConnectPlatformOut
<a id="schema-connectplatformout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `key` | string | да |  |
| `label` | string | да |  |
| `apps` | [ConnectAppOut](#schema-connectappout)[] | да |  |

## DashboardResponse
<a id="schema-dashboardresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `balance_kopeks` | integer | да |  |
| `subscription` | [SubscriptionOut](#schema-subscriptionout) \| null | да |  |
| `is_admin` | boolean | да |  |

## DeviceOut
<a id="schema-deviceout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `hwid` | string | да |  |
| `platform` | string | да |  |
| `device_model` | string | да |  |
| `created_at` | string (date-time) \| null | да |  |

## EmojiOut
<a id="schema-emojiout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `name` | string | да |  |
| `fallback` | string | да |  |
| `custom_id` | string | да |  |

## GiftPurchaseRequest
<a id="schema-giftpurchaserequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `period_days` | integer | да |  |
| `method` | string | да |  |

## GiftPurchaseResponse
<a id="schema-giftpurchaseresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `status` | string | да |  |
| `gift_link` | string \| null | нет |  |
| `payment_url` | string \| null | нет |  |

## HTTPValidationError
<a id="schema-httpvalidationerror"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `detail` | [ValidationError](#schema-validationerror)[] | нет |  |

## InfraBillingNodeOut
<a id="schema-infrabillingnodeout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `node_uuid` | string \| null | да |  |
| `node_name` | string | да |  |
| `provider_name` | string | да |  |
| `next_billing_at` | string (date-time) \| null | да |  |

## InfraBillingOut
<a id="schema-infrabillingout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `total_spent` | number | да |  |
| `current_month_payments` | number | да |  |
| `upcoming_nodes_count` | integer | да |  |
| `nodes` | [InfraBillingNodeOut](#schema-infrabillingnodeout)[] | да |  |

## LanguageRequest
<a id="schema-languagerequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `language` | string | да |  |

## LanguageResponse
<a id="schema-languageresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `language` | string | да |  |

## LtvResponse
<a id="schema-ltvresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `arpu_kopeks` | integer | да |  |
| `avg_ltv_paying_kopeks` | integer | да |  |
| `median_ltv_kopeks` | integer | да |  |
| `paying_users_count` | integer | да |  |
| `top_payers` | [TopPayerOut](#schema-toppayerout)[] | да |  |

## MassbanRequest
<a id="schema-massbanrequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `telegram_ids` | integer[] | да |  |

## MassbanResponse
<a id="schema-massbanresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `blocked_count` | integer | да |  |
| `requested_count` | integer | да |  |

## MessageRequest
<a id="schema-messagerequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `text` | string | да |  |

## MonitoringResponse
<a id="schema-monitoringresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `panel` | [PanelStatsOut](#schema-panelstatsout) | да |  |
| `nodes` | [NodeMetricOut](#schema-nodemetricout)[] | да |  |

## NetProfitOut
<a id="schema-netprofitout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `revenue_all_time` | number | да |  |
| `cost_all_time` | number | да |  |
| `net_profit_all_time` | number | да |  |
| `revenue_this_month` | number | да |  |
| `cost_this_month` | number | да |  |
| `net_profit_this_month` | number | да |  |

## NodeDetailOut
<a id="schema-nodedetailout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `uuid` | string | да |  |
| `name` | string | да |  |
| `country_code` | string | да |  |
| `is_connected` | boolean | да |  |
| `is_disabled` | boolean | да |  |
| `traffic_used_gb` | number | да |  |
| `address` | string | да |  |
| `port` | integer \| null | да |  |
| `is_connecting` | boolean | да |  |
| `users_online` | integer | да |  |
| `xray_uptime_seconds` | number | да |  |
| `last_status_change` | string (date-time) \| null | да |  |
| `last_status_message` | string \| null | да |  |
| `traffic_limit_gb` | number \| null | да |  |
| `traffic_reset_day` | integer \| null | да |  |
| `notify_percent` | integer \| null | да |  |
| `consumption_multiplier` | number | да |  |
| `tags` | string[] | да |  |
| `note` | string \| null | да |  |
| `provider_name` | string \| null | да |  |
| `versions` | [NodeVersionsOut](#schema-nodeversionsout) | да |  |
| `system` | object \| null | да |  |
| `created_at` | string (date-time) | да |  |
| `updated_at` | string (date-time) | да |  |

## NodeMetricOut
<a id="schema-nodemetricout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `node_uuid` | string | да |  |
| `node_name` | string | да |  |
| `users_online` | integer | да |  |
| `inbound_stats` | [NodeMetricStat](#schema-nodemetricstat)[] | да |  |
| `outbound_stats` | [NodeMetricStat](#schema-nodemetricstat)[] | да |  |

## NodeMetricStat
<a id="schema-nodemetricstat"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `tag` | string | да |  |
| `upload` | string | да |  |
| `download` | string | да |  |

## NodeOut
<a id="schema-nodeout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `uuid` | string | да |  |
| `name` | string | да |  |
| `country_code` | string | да |  |
| `is_connected` | boolean | да |  |
| `is_disabled` | boolean | да |  |
| `traffic_used_gb` | number | да |  |

## NodeVersionsOut
<a id="schema-nodeversionsout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `xray` | string \| null | да |  |
| `node` | string \| null | да |  |

## OverviewResponse
<a id="schema-overviewresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `revenue_today_kopeks` | integer | да |  |
| `revenue_7d_kopeks` | integer | да |  |
| `revenue_30d_kopeks` | integer | да |  |
| `revenue_all_time_kopeks` | integer | да |  |
| `active_subscriptions` | integer | да |  |
| `paying_subscriptions` | integer | да |  |
| `new_paying_subscriptions_today` | integer | да |  |
| `total_users` | integer | да |  |
| `new_users_7d` | integer | да |  |
| `conversion_percent` | number | да |  |
| `avg_check_kopeks` | integer | да |  |
| `mrr_kopeks` | integer | да |  |
| `arr_kopeks` | integer | да |  |
| `churn_percent_30d` | number | да |  |
| `total_traffic_gb` | number | да |  |
| `trial_started_count` | integer | да |  |
| `paying_users_count` | integer | да |  |
| `renewed_users_count` | integer | да |  |

## PanelStatsOut
<a id="schema-panelstatsout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `cpu_cores` | integer | да |  |
| `memory_used_bytes` | integer | да |  |
| `memory_total_bytes` | integer | да |  |
| `uptime_seconds` | number | да |  |
| `users_online_now` | integer | да |  |
| `users_online_last_day` | integer | да |  |
| `users_online_last_week` | integer | да |  |
| `users_never_online` | integer | да |  |
| `nodes_online` | integer | да |  |
| `nodes_total_bytes_lifetime` | integer | да |  |

## PaymentMethodOut
<a id="schema-paymentmethodout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | string | да |  |
| `label` | string | да |  |

## PeriodOut
<a id="schema-periodout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `days` | integer | да |  |
| `label` | string | да |  |
| `price_kopeks` | integer | да |  |
| `original_price_kopeks` | integer \| null | нет |  |

## PreviewRequest
<a id="schema-previewrequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `template` | string \| null | нет |  |
| `button_text` | string \| null | нет |  |

## PreviewResponse
<a id="schema-previewresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `html` | string | да |  |
| `visible_length` | integer | да |  |
| `warnings` | string[] | да |  |
| `button_text` | string \| null | нет |  |

## ProfileResponse
<a id="schema-profileresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `telegram_id` | integer | да |  |
| `username` | string \| null | да |  |
| `full_name` | string \| null | да |  |
| `language` | string | да |  |
| `balance_kopeks` | integer | да |  |
| `created_at` | string (date-time) | да |  |

## PromoCodeCreateRequest
<a id="schema-promocodecreaterequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `code` | string | да | длина ≥ 1, длина ≤ 32 |
| `type` | enum: `balance` \| `days` | да |  |
| `value` | integer | да | > 0.0 |
| `max_activations` | integer | нет | > 0.0, по умолчанию `1` |
| `expires_at` | string (date-time) \| null | нет |  |

## PromoCodeOut
<a id="schema-promocodeout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | integer | да |  |
| `code` | string | да |  |
| `type` | enum: `balance` \| `days` | да |  |
| `value` | integer | да |  |
| `max_activations` | integer | да |  |
| `activations_count` | integer | да |  |
| `expires_at` | string (date-time) \| null | да |  |
| `is_active` | boolean | да |  |
| `created_at` | string (date-time) | да |  |

## PromoCodeRequest
<a id="schema-promocoderequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `code` | string | да |  |

## PromoCodeResponse
<a id="schema-promocoderesponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `type` | string | да |  |
| `value` | integer | да |  |

## PromoCodeUpdateRequest
<a id="schema-promocodeupdaterequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `is_active` | boolean | да |  |

## PromoGroupCreateRequest
<a id="schema-promogroupcreaterequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `name` | string | да | длина ≥ 1, длина ≤ 64 |
| `discount_percent` | integer | да | ≥ 0.0, ≤ 100.0 |

## PromoGroupOut
<a id="schema-promogroupout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | integer | да |  |
| `name` | string | да |  |
| `discount_percent` | integer | да |  |
| `users_count` | integer | да |  |

## PromoGroupUpdateRequest
<a id="schema-promogroupupdaterequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `name` | string \| null | нет |  |
| `discount_percent` | integer \| null | нет |  |

## PurchaseRequest
<a id="schema-purchaserequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `tariff_id` | integer | да |  |
| `period_days` | integer | да |  |
| `method` | string | да |  |

## PurchaseResponse
<a id="schema-purchaseresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `status` | string | да |  |
| `payment_url` | string \| null | нет |  |
| `subscription` | [SubscriptionOut](#schema-subscriptionout) \| null | нет |  |

## RecentPaymentOut
<a id="schema-recentpaymentout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `user_id` | integer | да |  |
| `telegram_id` | integer | да |  |
| `username` | string \| null | да |  |
| `full_name` | string \| null | да |  |
| `amount_kopeks` | integer | да |  |
| `type` | string | да |  |
| `created_at` | string (date-time) | да |  |

## ReferralCommissionRequest
<a id="schema-referralcommissionrequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `commission_percent` | integer \| null | нет |  |

## ReferralFunnelResponse
<a id="schema-referralfunnelresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `referred_users_count` | integer | да |  |
| `referred_paying_count` | integer | да |  |
| `conversion_percent` | number | да |  |
| `total_earnings_kopeks` | integer | да |  |
| `top_referrers` | [TopReferrerOut](#schema-topreferrerout)[] | да |  |

## ReferralResponse
<a id="schema-referralresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `referral_link` | string | да |  |
| `percent` | integer | да |  |
| `invited_count` | integer | да |  |
| `earned_kopeks` | integer | да |  |
| `invite_bonus_days` | integer | да |  |

## RevenueByProviderDayOut
<a id="schema-revenuebyproviderdayout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `provider` | string | да |  |
| `values` | integer[] | да |  |

## RevenueByProviderOut
<a id="schema-revenuebyproviderout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `provider` | string | да |  |
| `revenue_kopeks` | integer | да |  |

## RevenueByTypeOut
<a id="schema-revenuebytypeout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `type` | string | да |  |
| `revenue_kopeks` | integer | да |  |

## RevenueByWeekdayOut
<a id="schema-revenuebyweekdayout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `weekday` | integer | да |  |
| `revenue_kopeks` | integer | да |  |

## RevenueCompositionResponse
<a id="schema-revenuecompositionresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `days` | string[] | да |  |
| `series` | [RevenueByProviderDayOut](#schema-revenuebyproviderdayout)[] | да |  |

## RevenuePointOut
<a id="schema-revenuepointout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `date` | string | да |  |
| `revenue_kopeks` | integer | да |  |
| `count` | integer | да |  |

## SalesBreakdownResponse
<a id="schema-salesbreakdownresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `by_type` | [RevenueByTypeOut](#schema-revenuebytypeout)[] | да |  |
| `by_provider` | [RevenueByProviderOut](#schema-revenuebyproviderout)[] | да |  |
| `by_weekday` | [RevenueByWeekdayOut](#schema-revenuebyweekdayout)[] | да |  |
| `active_subs_by_tariff` | [ActiveSubsByTariffOut](#schema-activesubsbytariffout)[] | да |  |

## SetUserPromoGroupRequest
<a id="schema-setuserpromogrouprequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `promo_group_id` | integer \| null | нет |  |

## SubscriptionDaysAdjustRequest
<a id="schema-subscriptiondaysadjustrequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `days` | integer | да |  |

## SubscriptionListResponse
<a id="schema-subscriptionlistresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `items` | [AdminSubscriptionListItem](#schema-adminsubscriptionlistitem)[] | да |  |
| `total` | integer | да |  |
| `page` | integer | да |  |
| `total_pages` | integer | да |  |

## SubscriptionOut
<a id="schema-subscriptionout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `status` | string | да |  |
| `end_date` | string (date-time) | да |  |
| `traffic_limit_gb` | integer | да |  |
| `traffic_used_gb` | number | да |  |
| `device_limit` | integer | да |  |
| `subscription_url` | string \| null | да |  |
| `tariff_id` | integer | да |  |
| `tariff_name` | string | да |  |
| `is_trial` | boolean | да |  |

## SubscriptionPulseOut
<a id="schema-subscriptionpulseout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `new_today` | integer | да |  |
| `renewals_today` | integer | да |  |
| `expiring_24h` | integer | да |  |
| `expiring_3d` | integer | да |  |

## SupportMessageOut
<a id="schema-supportmessageout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | integer | да |  |
| `direction` | string | да |  |
| `body` | string | да |  |
| `created_at` | string (date-time) | да |  |

## SupportReplyRequest
<a id="schema-supportreplyrequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `text` | string | да |  |

## SupportThreadDetailResponse
<a id="schema-supportthreaddetailresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `ticket_id` | integer | да |  |
| `status` | string | да |  |
| `assigned_admin_name` | string \| null | да |  |
| `user_id` | integer | да |  |
| `telegram_id` | integer | да |  |
| `username` | string \| null | да |  |
| `full_name` | string \| null | да |  |
| `messages` | [SupportMessageOut](#schema-supportmessageout)[] | да |  |

## SupportThreadOut
<a id="schema-supportthreadout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `ticket_id` | integer | да |  |
| `status` | string | да |  |
| `assigned_admin_name` | string \| null | да |  |
| `user_id` | integer | да |  |
| `telegram_id` | integer | да |  |
| `username` | string \| null | да |  |
| `full_name` | string \| null | да |  |
| `last_message` | string | да |  |
| `last_message_at` | string (date-time) | да |  |
| `unread` | boolean | да |  |

## SyncResultResponse
<a id="schema-syncresultresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `status` | string | да |  |
| `subscription` | [AdminSubscriptionOut](#schema-adminsubscriptionout) \| null | нет |  |

## TariffChangePreviewResponse
<a id="schema-tariffchangepreviewresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `price_kopeks` | integer | да |  |
| `remaining_days` | integer | да |  |

## TariffChangeRequest
<a id="schema-tariffchangerequest"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `tariff_id` | integer | да |  |

## TariffResponse
<a id="schema-tariffresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | integer | да |  |
| `name` | string | да |  |
| `device_limit` | integer | да |  |
| `traffic_limit_gb` | integer | да |  |
| `periods` | [PeriodOut](#schema-periodout)[] | да |  |
| `payment_methods` | [PaymentMethodOut](#schema-paymentmethodout)[] | да |  |

## TariffsResponse
<a id="schema-tariffsresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `tariffs` | [TariffResponse](#schema-tariffresponse)[] | да |  |
| `discount_percent` | integer | нет | по умолчанию `0` |
| `discount_expires_at` | string (date-time) \| null | нет |  |
| `balance_kopeks` | integer | нет | по умолчанию `0` |

## TemplateOut
<a id="schema-templateout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `key` | string | да |  |
| `group` | string | да |  |
| `title` | string | да |  |
| `trigger` | string | да |  |
| `template` | string | да |  |
| `variables` | string[] | да |  |
| `default_template` | string | да |  |
| `is_customized` | boolean | да |  |
| `enabled` | boolean | да |  |
| `button_text` | string \| null | нет |  |
| `default_button_text` | string \| null | нет |  |
| `variable_docs` | [VariableDocOut](#schema-variabledocout)[] | да |  |
| `required_variables` | string[] | да |  |
| `updated_at` | string (date-time) \| null | нет |  |
| `updated_by` | string \| null | нет |  |

## TemplateUpdateRequest
<a id="schema-templateupdaterequest"></a>

Частичное обновление: применяются только переданные поля. `template: null` возвращает заводской текст,
`button_text: null` — заводскую подпись кнопки.

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `template` | string \| null | нет |  |
| `button_text` | string \| null | нет |  |
| `enabled` | boolean \| null | нет |  |

## TopPayerOut
<a id="schema-toppayerout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `user_id` | integer | да |  |
| `telegram_id` | integer | да |  |
| `username` | string \| null | да |  |
| `full_name` | string \| null | да |  |
| `total_kopeks` | integer | да |  |

## TopReferrerOut
<a id="schema-topreferrerout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `user_id` | integer | да |  |
| `telegram_id` | integer | да |  |
| `username` | string \| null | да |  |
| `full_name` | string \| null | да |  |
| `earnings_kopeks` | integer | да |  |
| `referred_count` | integer | да |  |

## TransactionListResponse
<a id="schema-transactionlistresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `items` | [AdminTransactionListItem](#schema-admintransactionlistitem)[] | да |  |
| `total` | integer | да |  |
| `page` | integer | да |  |
| `total_pages` | integer | да |  |

## TransactionOut
<a id="schema-transactionout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `id` | integer | да |  |
| `type` | string | да |  |
| `amount_kopeks` | integer | да |  |
| `status` | string | да |  |
| `description` | string \| null | да |  |
| `created_at` | string (date-time) | да |  |

## UserNodeTrafficOut
<a id="schema-usernodetrafficout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `node_uuid` | string | да |  |
| `node_name` | string | да |  |
| `country_code` | string | да |  |
| `total_bytes` | integer | да |  |

## ValidationError
<a id="schema-validationerror"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `loc` | string \| integer[] | да |  |
| `msg` | string | да |  |
| `type` | string | да |  |

## VariableDocOut
<a id="schema-variabledocout"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `name` | string | да |  |
| `description` | string | да |  |
| `example` | string | да |  |

## app__cabinet__admin_schemas__PaginatedTransactionsResponse
<a id="schema-app-cabinet-admin-schemas-paginatedtransactionsresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `items` | [AdminTransactionOut](#schema-admintransactionout)[] | да |  |
| `total` | integer | да |  |
| `page` | integer | да |  |
| `total_pages` | integer | да |  |

## app__cabinet__schemas__PaginatedTransactionsResponse
<a id="schema-app-cabinet-schemas-paginatedtransactionsresponse"></a>

| Поле | Тип | Обязательное | Примечание |
|---|---|---|---|
| `items` | [TransactionOut](#schema-transactionout)[] | да |  |
| `total` | integer | да |  |
| `page` | integer | да |  |
| `total_pages` | integer | да |  |
