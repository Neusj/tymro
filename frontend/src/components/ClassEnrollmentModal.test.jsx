import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  classesApi: {
    enrollableStudents: vi.fn(),
    enrolledStudents: vi.fn(),
  },
  classTemplatesApi: {
    enrollableStudents: vi.fn(),
  },
  enrollmentsApi: {
    create: vi.fn(),
    cancel: vi.fn(),
  },
}))

import { classesApi, enrollmentsApi } from '../api/client'
import ClassEnrollmentModal from './ClassEnrollmentModal'

const gymClass = {
  id: 101,
  name: 'BJJ',
}

const candidate = {
  id: 11,
  name: 'Ana Perez',
  email: 'ana@test.local',
  username: 'ana',
  available_classes: 4,
  has_available_classes: true,
  unlimited_classes: false,
  plan_expiry_alert_level: 'safe',
  plan_expiry_alert_message: 'Plan vigente',
}

const enrolled = {
  ...candidate,
  student_id: 11,
  enrollment_id: 77,
}

beforeEach(() => {
  vi.clearAllMocks()
  classesApi.enrollableStudents.mockResolvedValue([candidate])
  classesApi.enrolledStudents.mockResolvedValue([enrolled])
  enrollmentsApi.create.mockResolvedValue({ id: 1, gym_class: 101 })
  enrollmentsApi.cancel.mockResolvedValue({})
})

describe('ClassEnrollmentModal', () => {
  it('cierra el modal despues de inscribir seleccionados', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const onChanged = vi.fn()

    render(
      <ClassEnrollmentModal
        open
        gymClass={gymClass}
        initialView="enroll"
        onClose={onClose}
        onChanged={onChanged}
      />,
    )

    await screen.findByText('Ana Perez')
    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar Ana Perez' }))
    await user.click(screen.getByRole('button', { name: 'Inscribir seleccionados' }))

    await waitFor(() => expect(enrollmentsApi.create).toHaveBeenCalledWith({
      gym_class: 101,
      student: 11,
      status: 'active',
    }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(onClose).toHaveBeenCalled()
  })

  it('cierra el modal despues de quitar seleccionados', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const onChanged = vi.fn()

    render(
      <ClassEnrollmentModal
        open
        gymClass={gymClass}
        initialView="enrolled"
        onClose={onClose}
        onChanged={onChanged}
      />,
    )

    const row = (await screen.findByText('Ana Perez')).closest('label')
    await user.click(within(row).getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Quitar seleccionados' }))

    await waitFor(() => expect(enrollmentsApi.cancel).toHaveBeenCalledWith(77))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(onClose).toHaveBeenCalled()
  })

  it('preselecciona FEFO y permite cambiar la membresía antes de inscribir', async () => {
    const user = userEvent.setup()
    classesApi.enrollableStudents.mockResolvedValue([{
      ...candidate,
      usable_plans: [
        { id: 21, plan_name: 'Plan próximo', end_date: '2026-09-30', remaining_classes: 2 },
        { id: 22, plan_name: 'Plan largo', end_date: '2026-12-31', remaining_classes: 8 },
      ],
    }])

    render(<ClassEnrollmentModal open gymClass={gymClass} onClose={vi.fn()} onChanged={vi.fn()} />)

    expect(await screen.findByText(/Se utilizará: Plan próximo/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cambiar' }))
    await user.selectOptions(screen.getByRole('combobox', { name: 'Membresía para Ana Perez' }), '22')
    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar Ana Perez' }))
    await user.click(screen.getByRole('button', { name: 'Inscribir seleccionados' }))

    await waitFor(() => expect(enrollmentsApi.create).toHaveBeenCalledWith({
      gym_class: 101,
      student: 11,
      status: 'active',
      student_plan_id: 22,
    }))
  })
})
