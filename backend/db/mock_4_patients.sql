-- Mock dataset: 4 patient rows only
-- Safe to run multiple times thanks to ON CONFLICT(phone)

INSERT INTO patients (
  id,
  phone,
  first_name,
  last_name,
  date_of_birth,
  sex,
  email,
  blood_type,
  address
)
VALUES
  (
    '91000000-0000-0000-0000-000000000001',
    '+33670000001',
    'Alice',
    'Example',
    '1993-05-17',
    'female',
    'alice.example@example.test',
    'A+',
    '1 Rue des Tests, Paris'
  ),
  (
    '91000000-0000-0000-0000-000000000002',
    '+33670000002',
    'Bruno',
    'Sample',
    '1988-11-02',
    'male',
    'bruno.sample@example.test',
    'O-',
    '2 Avenue des Tests, Marseille'
  ),
  (
    '91000000-0000-0000-0000-000000000003',
    '+33670000003',
    'Chloe',
    'Demo',
    '1979-01-26',
    'female',
    'chloe.demo@example.test',
    'B+',
    '3 Boulevard des Tests, Lille'
  ),
  (
    '91000000-0000-0000-0000-000000000004',
    '+33670000004',
    'Dorian',
    'Mock',
    '1997-09-09',
    'male',
    'dorian.mock@example.test',
    'AB+',
    '4 Place des Tests, Nantes'
  )
ON CONFLICT (phone) DO UPDATE
SET
  first_name = EXCLUDED.first_name,
  last_name = EXCLUDED.last_name,
  date_of_birth = EXCLUDED.date_of_birth,
  sex = EXCLUDED.sex,
  email = EXCLUDED.email,
  blood_type = EXCLUDED.blood_type,
  address = EXCLUDED.address,
  updated_at = now();
