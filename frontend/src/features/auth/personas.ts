import type { SyntheticPersona } from '../../types/auth'

export const SYNTHETIC_PERSONAS: Record<string, SyntheticPersona> = {
  dr_chen: {
    key: 'dr_chen',
    name: 'Dr. Sarah Chen, MD',
    role: 'clinician_reviewer',
    roleLabel: 'REVIEWER',
    scope: 'Clinician Reviewer (All Cases)',
    credentials: {
      username: 'dr_chen',
      password: 'synthetic-demo-pass-dr-chen',
    },
  },
  dr_ross: {
    key: 'dr_ross',
    name: 'Dr. Allison Ross, MD',
    role: 'clinician_reviewer',
    roleLabel: 'REVIEWER',
    scope: 'Clinician Reviewer (CASE-SYN-001 Only)',
    credentials: {
      username: 'dr_ross',
      password: 'synthetic-demo-pass-dr-ross',
    },
  },
  auditor_jane: {
    key: 'auditor_jane',
    name: 'Jane Doe',
    role: 'auditor',
    roleLabel: 'AUDITOR',
    scope: 'Auditor (Read-Only Observer)',
    credentials: {
      username: 'auditor_jane',
      password: 'synthetic-demo-pass-auditor-jane',
    },
  },
  admin_alex: {
    key: 'admin_alex',
    name: 'Alex Rivera',
    role: 'admin',
    roleLabel: 'ADMIN',
    scope: 'System Administrator (Full Access)',
    credentials: {
      username: 'admin_alex',
      password: 'synthetic-demo-pass-admin-alex',
    },
  },
}
