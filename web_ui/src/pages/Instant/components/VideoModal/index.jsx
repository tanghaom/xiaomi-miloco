/**
 * Copyright (C) 2025 Xiaomi Corporation
 * This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
 */

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Modal } from 'antd'
import { useTranslation } from 'react-i18next'
import { Icon } from '@/components';
import styles from './index.module.less'

const DEFAULT_VIEWPORT = { width: 1280, height: 720 }
const readViewportSize = () => {
  if (typeof window === 'undefined') {
    return DEFAULT_VIEWPORT
  }
  return { width: window.innerWidth, height: window.innerHeight }
}

/**
 * VideoModal Component - Video playback modal with canvas content synchronization
 * 视频放大播放Modal组件 - 带有canvas内容同步的视频播放模态框
 *
 * @param {Object} props - Component props
 * @param {boolean} props.visible - Whether modal is visible
 * @param {Function} props.onClose - Close callback function
 * @param {Object} props.sourceCanvasRef - Source canvas ref from VideoPlayer
 * @param {Object} [props.deviceInfo={}] - Device information object
 * @param {number} [props.channelCount=1] - Number of channels
 * @param {number} [props.currentChannel=0] - Current channel number
 * @param {Function} props.onChannelChange - Channel change callback function
 * @returns {JSX.Element} Video modal component
 */
const VideoModal = ({
  visible,
  onClose,
  sourceCanvasRef,
  deviceInfo = {},
  channelCount = 1,
  currentChannel = 0,
  onChannelChange
}) => {
  const modalCanvasRef = useRef(null)
  const animationFrameRef = useRef(null)
  const { t } = useTranslation()
  const [viewport, setViewport] = useState(readViewportSize)
  // 简单判断是否为移动端，用于控制 Modal 全屏展示，避免视频内容超出视口
  const isMobile = viewport.width <= 768

  useEffect(() => {
    if (typeof window === 'undefined') {
      return undefined
    }
    const handleResize = () => {
      setViewport(prev => {
        const next = readViewportSize()
        if (prev.width === next.width && prev.height === next.height) {
          return prev
        }
        return next
      })
    }
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
    }
  }, [])

  // 根据当前视口动态计算桌面端弹窗和画布的可用尺寸，提升观感
  const availableWidth = Math.max(viewport.width - 80, 480)
  const desktopModalWidth = Math.min(availableWidth, 1920)
  const desktopBodyMaxHeight = Math.min(Math.max(viewport.height - 120, 480), 1080)
  const desktopCanvasMaxHeight = Math.max(desktopBodyMaxHeight - 40, 360)

  // copy canvas content to canvas in Modal
  const copyCanvasContent = useCallback(() => {
    if (!sourceCanvasRef?.current || !modalCanvasRef.current || !visible) {
      return
    }

    try {
      const sourceCanvas = sourceCanvasRef.current
      const modalCanvas = modalCanvasRef.current
      const modalCtx = modalCanvas.getContext('2d')

      if (modalCanvas.width !== sourceCanvas.width || modalCanvas.height !== sourceCanvas.height) {
        modalCanvas.width = sourceCanvas.width
        modalCanvas.height = sourceCanvas.height
      }

      if (sourceCanvas.width > 0 && sourceCanvas.height > 0) {
        modalCtx.drawImage(sourceCanvas, 0, 0)
      }

      if (visible) {
        animationFrameRef.current = requestAnimationFrame(copyCanvasContent)
      }
    } catch {
      if (visible) {
        setTimeout(() => copyCanvasContent(), 100)
      }
    }
  }, [visible, sourceCanvasRef])

  // start/stop canvas content synchronization
  useEffect(() => {
    if (visible && sourceCanvasRef?.current && modalCanvasRef.current) {
      copyCanvasContent()
    } else if (visible) {
      const timer = setTimeout(() => {
        if (modalCanvasRef.current && sourceCanvasRef?.current) {
          copyCanvasContent()
        }
      }, 100)
      return () => clearTimeout(timer)
    }

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current)
        animationFrameRef.current = null
      }
    }
  }, [visible, copyCanvasContent, sourceCanvasRef])

  // ensure Modal canvas DOM is rendered
  useLayoutEffect(() => {
    if (visible && modalCanvasRef.current && sourceCanvasRef?.current) {
      copyCanvasContent()
    }
  }, [visible, copyCanvasContent, sourceCanvasRef])

  const handleChannelChange = useCallback(() => {
    if (channelCount > 1 && onChannelChange) {
      onChannelChange()
    }
  }, [channelCount, onChannelChange])

  const handleClose = useCallback(() => {
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current)
      animationFrameRef.current = null
    }
    onClose && onClose()
  }, [onClose])

  const modalWidth = isMobile ? '100%' : desktopModalWidth
  const modalStyle = isMobile
    ? {
        maxWidth: '100%',
        width: '100%',
        top: 0,
        padding: 0
      }
    : {
        maxWidth: 'calc(100vw - 64px)',
        width: 'auto',
        top: 20,
        padding: 0
      }

  const modalBodyStyle = isMobile
    ? {
        padding: 0,
        background: '#000',
        borderRadius: 0,
        overflow: 'hidden',
        height: '100vh'
      }
    : {
        padding: 0,
        background: '#000',
        borderRadius: '8px',
        overflow: 'hidden',
        maxHeight: desktopBodyMaxHeight
      }
  const canvasMaxHeight = isMobile ? '100vh' : `${desktopCanvasMaxHeight}px`

  return (
    <Modal
      open={visible}
      onCancel={handleClose}
      footer={null}
      width={modalWidth}
      style={modalStyle}
      bodyStyle={modalBodyStyle}
      destroyOnClose={true}
      closable={false}
      maskClosable={true}
      centered={true}
      styles={{
        mask: { backgroundColor: 'rgba(0, 0, 0, 0.8)' }
      }}
      className={styles.contentModal}
    >
      <div className={styles.videoModalContainer}>
        <div className={styles.videoArea}>
          <canvas
            ref={modalCanvasRef}
            style={{
              width: '100%',
              height: 'auto',
              /* 限制最大高度，移动端使用视口高度，桌面端保留一定边距 */
              maxHeight: canvasMaxHeight,
              borderRadius: '8px',
              objectFit: 'contain',
              background: '#000'
            }}
          />
        </div>

        <div className={styles.topBar}>
          <div className={styles.deviceInfo}>
            <span className={styles.deviceName}>
              {deviceInfo.room_name || t('instant.deviceList.noDevice')}
            </span>
            {deviceInfo.name && (
              <span className={styles.deviceSubName}>
                - {deviceInfo.name}
              </span>
            )}
          </div>
          <div className={styles.controls}>
            <div
              className={styles.controlButton}
              onClick={handleClose}
              title={t('common.close')}
            >
              <Icon
                name="close"
                width={16}
                height={16}
                style={{ color: '#fff' }}
              />
            </div>
          </div>
        </div>
      </div>
    </Modal>
  )
}

export default VideoModal
