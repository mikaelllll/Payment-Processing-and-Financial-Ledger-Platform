import { describe, expect, it } from 'vitest'

import { errorMessage } from './api'

describe('errorMessage', () => {
  it('returns FastAPI string details unchanged', () => {
    expect(errorMessage('Payment not found', 404)).toBe('Payment not found')
  })

  it('formats FastAPI validation issues without object coercion', () => {
    expect(errorMessage([
      { loc: ['body', 'amount'], msg: 'Input should be greater than 0' },
      { loc: ['body', 'idempotency_key'], msg: 'Field required' },
    ], 422)).toBe(
      'amount: Input should be greater than 0; idempotency_key: Field required',
    )
  })

  it('uses a safe fallback for unknown response bodies', () => {
    expect(errorMessage({ unexpected: true }, 500)).toBe('Request failed (500)')
  })
})
