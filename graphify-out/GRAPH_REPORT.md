# Graph Report - Marinade  (2026-10-06)

## Corpus Check
- 86 files · ~61,646 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 6 file(s) not represented in the graph (top: (none) 3, .example 1, .ini 1)

## Summary
- 1397 nodes · 4554 edges · 55 communities (34 shown, 21 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 632 edges (avg confidence: 0.94)
- Token cost: 120,844 input · 0 output

## Community Hubs (Navigation)
- Restaurant API Routes
- Exception Handling & Services
- Auth & Two-Factor
- Tenant Auth Dependencies
- Operators & Payment Security
- Reservations & Waitlist
- ROS API Routes
- Subscriptions & Daily Balance
- Config & Alembic Env
- Commande Orders & Refunds
- Composant Stock Models
- Alembic Migrations
- Subscription API Routes
- ROS Orders & Sessions
- Menus & Categories
- POS Transactions
- Restaurant & Stock Repos
- ROS Domain Models
- Repository & Service Packages
- ROS Service
- App Startup & Routing
- Plat Recipe Components
- Payment Service
- Notification Service Tests
- Notification Templates
- Boissons (Drinks)
- Refresh Tokens
- WhatsApp Notifications
- Combinaisons (Combos)
- EasyTransact Payment Adapter
- Architecture & Dependencies Docs
- Plats (Dishes)
- Tables
- Orange Money Payment
- Schema & Roles (Docs)
- Enums
- Notification Channel Tests
- P0 Plan & Tenant Migration
- Stock BOM Concepts
- Base Repository
- Email Notifications
- Notification Channel ABC
- SMS Notifications
- Payment Factory
- Cash Payment
- Mobile Money Payment
- Notification Factory
- Market Positioning
- Dual Order Model
- Restaurant Customization
- Docker Compose (empty)

## God Nodes (most connected - your core abstractions)
1. `User` - 91 edges
2. `RosService` - 75 edges
3. `CommandeService` - 57 edges
4. `BaseRepository` - 48 edges
5. `NotFoundError` - 44 edges
6. `AuthService` - 43 edges
7. `UserRepository` - 38 edges
8. `SubscriptionService` - 38 edges
9. `BusinessLogicError` - 36 edges
10. `ValidationError` - 35 edges

## Surprising Connections (you probably didn't know these)
- `PlatComposant BOM (Bill of Materials)` --semantically_similar_to--> `combinaison_composants table`  [INFERRED] [semantically similar]
  .trae/documents/P0_implementation_plan.md → alembic_sql.txt
- `Automatic Stock Deduction on Commande` --semantically_similar_to--> `Stock Reservation Lifecycle`  [INFERRED] [semantically similar]
  .trae/documents/P0_implementation_plan.md → README.md
- `Commande Refund Workflow` --semantically_similar_to--> `transactions.idempotency_key`  [INFERRED] [semantically similar]
  .trae/documents/P0_implementation_plan.md → alembic_sql.txt
- `Restaurant Operating System Positioning` --semantically_similar_to--> `Hybrid Subscription + Restaurant Operations Model`  [INFERRED] [semantically similar]
  README.md → docs/POSITIONING_ANALYSIS.md
- `Marinade MVP Maturity Assessment` --conceptually_related_to--> `Composable Catalog (Composant -> Combinaison)`  [AMBIGUOUS]
  docs/POSITIONING_ANALYSIS.md → README.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Component Stock Lifecycle (reserve, consume, release, deduct)** — readme_stock_reservation, alembic_sql_stock_composants, alembic_sql_stock_mouvements, _trae_documents_p0_implementation_plan_auto_stock_deduction, _trae_documents_p0_implementation_plan_platcomposant_bom, alembic_sql_combinaison_composants [INFERRED 0.85]
- **Multi-tenant Isolation Mechanism** — alembic_sql_rls_tenant_isolation, alembic_sql_restaurant_members, readme_multi_tenant_isolation, docs_restaurant_guide_multi_tenant_configuration, _trae_documents_p0_implementation_plan_staffrole [INFERRED 0.85]
- **P0 Corrective Workstreams** — _trae_documents_p0_implementation_plan_commande_deprecation, _trae_documents_p0_implementation_plan_staffrole, _trae_documents_p0_implementation_plan_reservation_system, _trae_documents_p0_implementation_plan_auth_extensions, _trae_documents_p0_implementation_plan_platcomposant_bom [EXTRACTED 1.00]

## Communities (55 total, 21 thin omitted)

### Community 0 - "Restaurant API Routes"
Cohesion: 0.07
Nodes (96): add_commande_item(), add_plat_composant(), add_stock_movement(), approve_refund(), create_boisson(), create_combinaison(), create_commande(), create_composant() (+88 more)

### Community 1 - "Exception Handling & Services"
Cohesion: 0.05
Nodes (30): general_exception_handler(), marinade_exception_handler(), WaitlistEntry, TwoFactorSetupResponse, UserLogin, AuthService, _FallbackTOTP, _generate_random_base32() (+22 more)

### Community 2 - "Auth & Two-Factor"
Cohesion: 0.05
Nodes (39): confirm_two_factor(), disable_two_factor(), forgot_password(), _generate_2fa_secret(), _generate_recovery_codes(), get_two_factor_recovery_codes(), _hash_token(), login() (+31 more)

### Community 3 - "Tenant Auth Dependencies"
Cohesion: 0.05
Nodes (35): _authorize_tenant(), current_tenant_id(), get_current_user(), require_payment_intent_access(), require_restaurant_access(), require_staff_role(), require_subscription_access(), require_tenant_path() (+27 more)

### Community 4 - "Operators & Payment Security"
Cohesion: 0.06
Nodes (18): require_admin(), create_prefix(), list_prefixes(), update_prefix(), MobileOperatorPrefix, MobileOperatorPrefixCreate, MobileOperatorPrefixResponse, MobileOperatorPrefixUpdate (+10 more)

### Community 5 - "Reservations & Waitlist"
Cohesion: 0.11
Nodes (33): cancel_reservation(), check_in_reservation(), confirm_reservation(), create_reservation(), _create_reservation_guests(), create_waitlist_entry(), delete_reservation(), get_reservation() (+25 more)

### Community 6 - "ROS API Routes"
Cohesion: 0.12
Nodes (38): close_session(), close_shift(), create_customer(), create_order(), generate_procurement_suggestions(), get_active_sessions(), get_group_consolidated_reporting(), get_pending_tickets() (+30 more)

### Community 7 - "Subscriptions & Daily Balance"
Cohesion: 0.10
Nodes (7): DailyBalance, Subscription, SubscriptionTier, DailyBalanceRepository, SubscriptionRepository, SubscriptionTierRepository, SubscriptionService

### Community 8 - "Config & Alembic Env"
Cohesion: 0.06
Nodes (7): get_settings(), Settings, postgres_test_session(), _set_rls_context(), test_cors_lists_are_parsed(), test_database_url_is_built_from_parts(), test_dotenv_is_not_loaded_during_tests()

### Community 9 - "Commande Orders & Refunds"
Cohesion: 0.12
Nodes (8): Commande, CommandeItem, CommandeRefund, CombinaisonComposantRepository, CommandeItemRepository, CommandeRefundRepository, CommandeRepository, CommandeService

### Community 10 - "Composant Stock Models"
Cohesion: 0.13
Nodes (20): get_db(), CombinaisonComposant, Composant, StockComposant, StockMouvement, RosInvoice, RosInvoiceRepository, auth_headers() (+12 more)

### Community 11 - "Alembic Migrations"
Cohesion: 0.11
Nodes (10): upgrade(), upgrade(), upgrade(), upgrade(), _context_functions(), _rls(), upgrade(), upgrade() (+2 more)

### Community 12 - "Subscription API Routes"
Cohesion: 0.16
Nodes (24): create_daily_balance(), create_subscription(), create_tier(), get_current_balance(), get_my_subscription(), get_subscription(), get_subscription_balances(), get_tier() (+16 more)

### Community 13 - "ROS Orders & Sessions"
Cohesion: 0.11
Nodes (9): RosOrder, RosPaymentTransaction, ServiceSession, ProductionTicketRepository, RosCashShiftRepository, RosCustomerRepository, RosOrderRepository, RosPaymentRepository (+1 more)

### Community 14 - "Menus & Categories"
Cohesion: 0.14
Nodes (6): Menu, MenuCategory, MenuCategoryRepository, MenuRepository, MenuService, StockService

### Community 15 - "POS Transactions"
Cohesion: 0.17
Nodes (14): require_pos(), create_transaction(), get_my_transactions(), get_subscription_transactions(), get_transaction(), get_transaction_by_pos_id(), Transaction, RefreshTokenBase (+6 more)

### Community 16 - "Restaurant & Stock Repos"
Cohesion: 0.14
Nodes (5): Restaurant, RestaurantRepository, StockComposantRepository, StockMouvementRepository, RestaurantService

### Community 17 - "ROS Domain Models"
Cohesion: 0.33
Nodes (16): ProductionTicket, RosAuditLog, RosCashShift, RosCustomer, RosOrderItem, RosAuditLogRepository, CashShiftStatus, CustomerType (+8 more)

### Community 18 - "Repository & Service Packages"
Cohesion: 0.16
Nodes (3): NotificationTemplateManager, get_logger(), setup_logging()

### Community 20 - "App Startup & Routing"
Cohesion: 0.13
Nodes (6): get_engine(), get_session_local(), health_check(), lifespan(), root(), KdsConnectionManager

### Community 21 - "Plat Recipe Components"
Cohesion: 0.17
Nodes (4): PlatComposant, ComposantRepository, PlatComposantRepository, PlatComposantService

### Community 25 - "Boissons (Drinks)"
Cohesion: 0.24
Nodes (3): Boisson, BoissonRepository, BoissonService

### Community 26 - "Refresh Tokens"
Cohesion: 0.19
Nodes (3): RefreshToken, RefreshTokenRepository, TransactionRepository

### Community 28 - "Combinaisons (Combos)"
Cohesion: 0.23
Nodes (3): Combinaison, CombinaisonRepository, CombinaisonService

### Community 31 - "Architecture & Dependencies Docs"
Cohesion: 0.19
Nodes (13): Auth Extensions (reset password, email verify, 2FA), TOTP Two-Factor Authentication, AGENTS.md Project Guide, Custom Exception Hierarchy, JWT Authentication, Layered Architecture (API/Service/Repository/Model/Schema), Segmented Database Configuration, NotificationService (email, sms, whatsapp) (+5 more)

### Community 32 - "Plats (Dishes)"
Cohesion: 0.28
Nodes (3): Plat, PlatRepository, PlatService

### Community 33 - "Tables"
Cohesion: 0.29
Nodes (3): Table, TableRepository, TableService

### Community 35 - "Schema & Roles (Docs)"
Cohesion: 0.20
Nodes (10): Commande Refund Workflow, User Roles (admin, pos, restaurant), Alembic Offline SQL Dump, check_role_valid constraint, daily_balances table, Migration 20260914_1200 Users/Subscriptions/Transactions, Migration 20260915_1400 Restaurant Models, Migration 20260916_1000 Menu Combinations (+2 more)

### Community 36 - "Enums"
Cohesion: 0.44
Nodes (8): CommandeStatut, PaymentStatus, RefundStatus, StaffRole, SubscriptionStatus, TableStatut, UserRole, VerificationStatus

### Community 38 - "P0 Plan & Tenant Migration"
Cohesion: 0.25
Nodes (11): P0 Implementation Plan, P0 Alembic Migration 20260925_1700, Reservation & Waitlist System, Soft Delete (deleted_at), StaffRole (granular staff permissions), Migration 20260924_1200 Tenant Isolation & Payment Ledger, restaurant_members table, PostgreSQL RLS Tenant Isolation Policies (+3 more)

### Community 39 - "Stock BOM Concepts"
Cohesion: 0.27
Nodes (10): Automatic Stock Deduction on Commande, PlatComposant BOM (Bill of Materials), combinaison_composants table, Migration 20260916_1200 Component Stock & Recipe Quantities, stock_composants table, stock_mouvements table, Marinade MVP Maturity Assessment, Combinaison Recommendations by Availability (+2 more)

### Community 48 - "Market Positioning"
Cohesion: 0.25
Nodes (6): Marinade Positioning Analysis, Dunning Management, Hybrid Subscription + Restaurant Operations Model, Priority Roadmap Phases 1-4, SaaS Billing Platforms (Stripe, Chargebee, Recurly, Zuora), Restaurant Operating System Positioning

### Community 49 - "Dual Order Model"
Cohesion: 0.29
Nodes (6): Dual Order Model (Commande vs RosOrder), RosOrder, commandes table, Payment intents/events/ledger tables, PaymentService (cash, orange_money, mobile_money), Table Occupancy Lifecycle

### Community 51 - "Restaurant Customization"
Cohesion: 0.38
Nodes (7): Restaurant Subscription Niche (PizzaBox AI, Possier, Menutro, Ressto), Restaurant Customization Guide, Admin Studio (no-code, future), config_jsonb Advanced Restaurant Configuration, Configurable Business Rules (future), horaires_ouverture JSONB Opening Hours, Restaurant Subscription Tiers (Starter, Standard, Premium)

## Ambiguous Edges - Review These
- `Composable Catalog (Composant -> Combinaison)` → `Marinade MVP Maturity Assessment`  [AMBIGUOUS]
  docs/POSITIONING_ANALYSIS.md · relation: conceptually_related_to
- `Hybrid Subscription + Restaurant Operations Model` → `config_jsonb Advanced Restaurant Configuration`  [AMBIGUOUS]
  docs/RESTAURANT_GUIDE.md · relation: conceptually_related_to

## Knowledge Gaps
- **7 isolated node(s):** `RosOrder`, `Soft Delete (deleted_at)`, `Custom Exception Hierarchy`, `docker-compose.yml (empty)`, `Dunning Management` (+2 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 211 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Composable Catalog (Composant -> Combinaison)` and `Marinade MVP Maturity Assessment`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `User` connect `Auth & Two-Factor` to `Exception Handling & Services`, `Tenant Auth Dependencies`, `Operators & Payment Security`, `Reservations & Waitlist`, `ROS API Routes`, `Config & Alembic Env`, `Composant Stock Models`, `Alembic Migrations`, `POS Transactions`, `Repository & Service Packages`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Are the 51 inferred relationships involving `User` (e.g. with `_authorize_tenant()` and `get_current_user()`) actually correct?**
  _`User` has 51 INFERRED edges - model-reasoned connections that need verification._
- **What connects `RosOrder`, `Soft Delete (deleted_at)`, `Custom Exception Hierarchy` to the rest of the system?**
  _7 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Restaurant API Routes` be split into smaller, more focused modules?**
  _Cohesion score 0.07022518765638032 - nodes in this community are weakly interconnected._
- **What is the exact relationship between `Hybrid Subscription + Restaurant Operations Model` and `config_jsonb Advanced Restaurant Configuration`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `NotificationService` connect `Notification Service Tests` to `Exception Handling & Services`, `Payment Factory`, `Notification Factory`, `Repository & Service Packages`, `Notification Dispatch`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._