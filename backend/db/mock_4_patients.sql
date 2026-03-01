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
    'Amina',
    'Diallo',
    '1993-05-17',
    'female',
    'amina.diallo@example.com',
    'A+',
    '12 Rue Victor Hugo, Paris'
  ),
  (
    '91000000-0000-0000-0000-000000000002',
    '+33670000002',
    'Lucas',
    'Bernard',
    '1988-11-02',
    'male',
    'lucas.bernard@example.com',
    'O-',
    '4 Avenue de Lyon, Marseille'
  ),
  (
    '91000000-0000-0000-0000-000000000003',
    '+33670000003',
    'Nora',
    'Kone',
    '1979-01-26',
    'female',
    'nora.kone@example.com',
    'B+',
    '88 Rue Nationale, Lille'
  ),
  (
    '91000000-0000-0000-0000-000000000004',
    '+33670000004',
    'Yvan',
    'Kondjo',
    '1997-09-09',
    'male',
    'yvankondjo8@gmail.com',
    'AB+',
    '31 Rue de la Republique, Nantes'
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
