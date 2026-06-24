-- ============================================================================
-- Member Concierge AI — seed.sql
-- Datos de demostración. PIN demo para todos los socios: 1234
-- ============================================================================

-- Socios demo
select register_member('KORA-100001', '1234', 'María Fernanda López', 'maria@example.com', '+5215512345001');
select register_member('KORA-100002', '1234', 'Carlos Andrés Rivera', 'carlos@example.com', '+5215512345002');

-- Membresías
insert into memberships (member_id, tier, status, weeks_per_year, points_balance, start_date, end_date)
select id, 'platinum', 'active', 3, 45000, '2024-01-01', '2031-01-01'
from members where membership_no = 'KORA-100001';

insert into memberships (member_id, tier, status, weeks_per_year, points_balance, start_date, end_date)
select id, 'gold', 'active', 2, 18000, '2025-03-01', '2032-03-01'
from members where membership_no = 'KORA-100002';

-- Catálogo de beneficios
insert into benefits (code, name, description, tier_required) values
  ('UPGRADE',     'Upgrade de habitación', 'Mejora de categoría sujeta a disponibilidad', 'gold'),
  ('SPA',         'Acceso premium al spa', 'Circuito de hidroterapia incluido', 'gold'),
  ('AIRPORT',     'Transporte aeropuerto', 'Traslado privado de cortesía', 'platinum'),
  ('CONCIERGE',   'Concierge dedicado',   'Asistente personal 24/7', 'platinum'),
  ('LATE_CHECKOUT','Late check-out',       'Salida tardía hasta las 15:00', 'silver');

-- Reservaciones demo
insert into reservations (member_id, resort_name, room_type, check_in, check_out, guests, status, confirmation_code)
select id, 'Kora Riviera Maya', 'Suite Ocean View', '2026-07-12', '2026-07-19', 4, 'confirmed', 'CNF-7A19X2'
from members where membership_no = 'KORA-100001';

insert into reservations (member_id, resort_name, room_type, check_in, check_out, guests, status, confirmation_code)
select id, 'Kora Los Cabos', 'Junior Suite', '2026-09-05', '2026-09-10', 2, 'pending', 'CNF-9C05B7'
from members where membership_no = 'KORA-100002';

-- Estado de cuenta
insert into account_statements (member_id, period, amount_due, amount_paid, due_date, status, items)
select id, '2026-06', 0, 12500.00, '2026-06-10', 'paid',
       '[{"concept":"Mantenimiento anual","amount":12500.00}]'::jsonb
from members where membership_no = 'KORA-100001';

insert into account_statements (member_id, period, amount_due, amount_paid, due_date, status, items)
select id, '2026-06', 8900.00, 0, '2026-06-30', 'pending',
       '[{"concept":"Mantenimiento anual","amount":8900.00}]'::jsonb
from members where membership_no = 'KORA-100002';

-- Base de conocimiento (FAQ) — embeddings se generan luego con el script de ingestión
insert into knowledge_base (title, content, category) values
  ('Política de cancelación',
   'Las cancelaciones realizadas con más de 30 días de anticipación no tienen penalización. Entre 30 y 15 días aplica un cargo del 25%. Con menos de 15 días, 50%. Los socios Platinum y Signature tienen una cancelación flexible sin penalización al año.',
   'cancellation'),
  ('Cómo cambiar una reservación',
   'Puedes solicitar cambios de fecha o resort desde el portal o el chat, sujetos a disponibilidad. Los cambios con más de 21 días de anticipación no generan cargo. El concierge IA te muestra alternativas al instante.',
   'reservation'),
  ('Beneficios por nivel de membresía',
   'Silver incluye late check-out. Gold añade upgrades y acceso al spa. Platinum suma transporte al aeropuerto y concierge dedicado. Signature incluye experiencias exclusivas y semanas adicionales.',
   'benefits'),
  ('Estado de cuenta y pagos',
   'Tu estado de cuenta muestra la cuota de mantenimiento anual y cualquier consumo. Puedes pagar en línea con tarjeta o transferencia. Los avisos de vencimiento se envían por correo y WhatsApp.',
   'billing');
