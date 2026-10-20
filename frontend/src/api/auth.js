import { http } from './request'

/**
 * 鉴权相关接口（对应 docs/API.md 第 2 节）
 */

/** 获取图形验证码：data = { captcha_id, image } */
export function fetchCaptcha() {
  return http.get('/auth/captcha')
}

/**
 * 注册
 * @param {{ username: string, password: string, confirm_password: string, captcha_id: string, captcha_code: string }} payload
 * @returns {Promise<{ id: number, username: string }>}
 */
export function register(payload) {
  return http.post('/auth/register', payload)
}

/**
 * 登录
 * @param {{ username: string, password: string, captcha_id: string, captcha_code: string }} payload
 * @returns {Promise<{ access_token: string, token_type: string, user: { id: number, username: string } }>}
 */
export function login(payload) {
  return http.post('/auth/login', payload)
}

/** 当前用户：data = { id, username } */
export function fetchCurrentUser() {
  return http.get('/auth/me')
}
