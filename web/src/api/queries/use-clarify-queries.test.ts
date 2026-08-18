import { describe, expect, test } from 'vitest'
import { isAlreadyAnswered } from './use-clarify-queries'

describe('isAlreadyAnswered', () => {
  test('recognises the backend 409 text as "handled elsewhere", not a failure', () => {
    // The API answers a raced question with this exact Vietnamese sentence.
    const e = new Error('Câu hỏi này đã được trả lời hoặc đã hết hạn.')
    expect(isAlreadyAnswered(e)).toBe(true)
  })

  test('a real failure is not mistaken for a race', () => {
    expect(isAlreadyAnswered(new Error('500 Internal Server Error'))).toBe(false)
  })

  test('a non-Error rejection does not throw', () => {
    expect(isAlreadyAnswered('boom')).toBe(false)
    expect(isAlreadyAnswered(undefined)).toBe(false)
  })
})
