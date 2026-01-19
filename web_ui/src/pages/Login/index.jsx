/**
 * Copyright (C) 2025 Xiaomi Corporation
 * This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
 */

import React, { useCallback, useEffect, useState, useRef } from "react"
import CryptoJS from 'crypto-js'
import { useTranslation } from 'react-i18next';
import { useNavigate } from "react-router-dom"
import { Button, Input, message } from 'antd'
import { EyeInvisibleOutlined, EyeOutlined } from '@ant-design/icons'
import { getJudgeLogin, getPinLogin, getTurnstileConfig } from "@/api"
import { ContentModal, LanguageSwitcher } from "@/components";
import styles from './index.module.less'

/**
 * Login Page - User authentication page with PIN code login
 * 登录页面 - 使用PIN码进行用户身份验证的页面
 *
 * @returns {JSX.Element} Login page component
 */
const Login = () => {
  const [pin, setPin] = useState("")
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [turnstileConfig, setTurnstileConfig] = useState({ enabled: false, site_key: '' })
  const [turnstileToken, setTurnstileToken] = useState("")
  const [turnstileLoaded, setTurnstileLoaded] = useState(false)
  const inputRef = useRef(null)
  const turnstileRef = useRef(null)
  const turnstileWidgetId = useRef(null)
  const navigate = useNavigate()
  const { t } = useTranslation();

  // Load Turnstile script and config
  useEffect(() => {
    const loadTurnstile = async () => {
      try {
        const res = await getTurnstileConfig()
        if (res?.code === 0 && res.data?.enabled) {
          setTurnstileConfig(res.data)
          
          // Load Turnstile script if not already loaded
          if (!window.turnstile) {
            const script = document.createElement('script')
            script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
            script.async = true
            script.onload = () => setTurnstileLoaded(true)
            document.head.appendChild(script)
          } else {
            setTurnstileLoaded(true)
          }
        }
      } catch (error) {
        console.error('Failed to load Turnstile config:', error)
      }
    }
    loadTurnstile()
  }, [])

  // Render Turnstile widget when ready
  useEffect(() => {
    if (turnstileLoaded && turnstileConfig.enabled && turnstileRef.current && window.turnstile) {
      // Remove existing widget if any
      if (turnstileWidgetId.current) {
        window.turnstile.remove(turnstileWidgetId.current)
      }
      
      turnstileWidgetId.current = window.turnstile.render(turnstileRef.current, {
        sitekey: turnstileConfig.site_key,
        callback: (token) => {
          setTurnstileToken(token)
        },
        'expired-callback': () => {
          setTurnstileToken("")
        },
        'error-callback': () => {
          setTurnstileToken("")
          message.error(t('login.turnstileError') || 'Verification failed, please try again')
        },
        theme: 'light',
        size: 'normal'
      })
    }
    
    return () => {
      if (turnstileWidgetId.current && window.turnstile) {
        window.turnstile.remove(turnstileWidgetId.current)
      }
    }
  }, [turnstileLoaded, turnstileConfig])

  useEffect(() => {
    const fetchData = async () => {
      const res = await getJudgeLogin()
      const { code = 0, data: { is_registered } } = res
      if (code === 0 && !is_registered) {
        navigate("/setup")
        return
      }
    }
    fetchData()
    inputRef.current?.focus()
  }, [])

  // Reset Turnstile after failed login
  const resetTurnstile = useCallback(() => {
    if (turnstileWidgetId.current && window.turnstile) {
      window.turnstile.reset(turnstileWidgetId.current)
      setTurnstileToken("")
    }
  }, [])

  const handleSubmit = useCallback(async (inputPin) => {
    if (loading) {return;}
    if (inputPin.length !== 6) {return;}
    
    // Check Turnstile if enabled
    if (turnstileConfig.enabled && !turnstileToken) {
      message.warning(t('login.turnstileRequired') || 'Please complete the verification')
      return
    }
    
    setLoading(true)
    const res = await getPinLogin({ 
      username: 'admin', 
      password: CryptoJS.MD5(inputPin).toString(),
      turnstile_token: turnstileToken || undefined
    })
    setLoading(false)
    if (res?.code === 0) {
      message.success(t('login.loginSuccess'))
      navigate("/home")
    } else {
      message.error(res?.message || t('login.loginFail'))
      // Reset Turnstile after failed attempt
      resetTurnstile()
    }
  }, [loading, t, navigate, turnstileConfig.enabled, turnstileToken, resetTurnstile])

  return (
    <ContentModal>
      <LanguageSwitcher
        size="small"
        showIcon={true}
        showLabel={false}
        className={styles.loginLanguageSwitcher}
      />

      <h1 className={styles.title}>{t('login.pleaseLogin')}</h1>
      <div className={styles.form}>
        <div className={styles.inputGroup}>
          <div className={styles.label}>
            {t('login.inputPin')}
          </div>
          <div className={styles.otpContainer}>
            <Input.OTP
              ref={inputRef}
              length={6}
              type={showPassword ? "text" : "password"}
              size="large"
              onChange={(value) => {
                setPin(value)
                if (value.length === 6) {
                  handleSubmit(value)
                }
              }}
              style={{
                justifyContent: 'space-between',
                flex: 1,
              }}
            />
            <div
              className={styles.eyeIcon}
              onClick={() => setShowPassword(!showPassword)}
            >
              {showPassword ? <EyeOutlined /> : <EyeInvisibleOutlined />}
            </div>
          </div>
        </div>
        {/* Turnstile verification widget */}
        {turnstileConfig.enabled && (
          <div className={styles.turnstileContainer}>
            <div ref={turnstileRef}></div>
          </div>
        )}
        
        <Button
          onClick={() => handleSubmit(pin)}
          className={styles.button}
          type="primary"
          size="large"
          loading={loading}
          disabled={turnstileConfig.enabled && !turnstileToken}
        >
          {t('login.login')}
        </Button>
      </div>
    </ContentModal>
  )
}

export default Login
