/**
 * Copyright (C) 2025 Xiaomi Corporation
 * This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.
 */

import React, { useState } from 'react';
import { Empty, Modal, Button, message } from 'antd';
import { useTranslation } from 'react-i18next';
import { DownloadOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons';
import { zip } from 'fflate';
import styles from './ImageRecordModal.module.less';

/**
 * ImageRecordModal Component - Image record modal component
 * 图片记录弹窗组件
 *
 * @param {Object} props - Component props
 * @param {boolean} props.visible - Whether the modal is visible
 * @param {Function} props.onCancel - Function to cancel the modal
 * @param {Array} props.imageData - Image data
 * @returns {JSX.Element} ImageRecordModal component
 */
const ImageRecordModal = ({
  visible,
  onCancel,
  imageData = []
}) => {
  const { t } = useTranslation();
  // 图片预览状态
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewImageUrl, setPreviewImageUrl] = useState('');
  const [previewTitle, setPreviewTitle] = useState('');
  const [previewImages, setPreviewImages] = useState([]);
  const [previewIndex, setPreviewIndex] = useState(0);

  /**
   * 构造图片访问 URL，兼容相对路径与完整 URL
   * @param {string} imagePath
   * @returns {string}
   */
  const buildImageUrl = (imagePath) => {
    if (!imagePath) return '';
    if (imagePath.startsWith('/')) {
      return `${window.location.origin}${import.meta.env.VITE_API_BASE}${imagePath}`;
    }
    if (imagePath.startsWith('http')) {
      return imagePath;
    }
    return `${import.meta.env.VITE_API_BASE}/${imagePath}`;
  };

  // download all images of the specified camera (ZIP packaging)
  const downloadCameraImages = async (camera) => {
    if (!camera.images || camera.images.length === 0) {
      return;
    }

    try {
      const cameraName = camera.camera_info?.name || 'camera';
      // parallel download all images and add to ZIP
      const downloadPromises = camera.images.map(async (image, index) => {
        try {
          const imageUrl = image.data?.startsWith('/') ?
            `${window.location.origin}${import.meta.env.VITE_API_BASE}${image.data}` :
            (image.data?.startsWith('http') ? image.data : `${import.meta.env.VITE_API_BASE}/${image.data}`);

          const response = await fetch(imageUrl);
          if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
          }

          const blob = await response.blob();
          const arrayBuffer = await blob.arrayBuffer();
          const fileName = `${cameraName}_${String(index + 1).padStart(3, '0')}_${image.timestamp || Date.now()}.jpg`;

          return {
            fileName,
            data: new Uint8Array(arrayBuffer)
          };
        } catch (error) {
          console.error('downloadImageFailed:', image.timestamp, error);
          return null;
        }
      });

      // wait for all images to be downloaded
      const imageFiles = await Promise.all(downloadPromises);
      const validFiles = imageFiles.filter(file => file !== null);
      const zipFiles = {};
      validFiles.forEach(file => {
        zipFiles[file.fileName] = file.data;
      });


      const zipBlob = await new Promise((resolve, reject) => {
        zip(zipFiles, (err, data) => {
          if (err) {
            reject(err);
          } else {
            resolve(new Blob([data], { type: 'application/zip' }));
          }
        });
      });

      const downloadUrl = window.URL.createObjectURL(zipBlob);
      const link = document.createElement('a');
      const now = new Date();
      const timestamp = now.toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '_');
      link.href = downloadUrl;
      link.download = `${cameraName}_images_${timestamp}.zip`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(downloadUrl);

      console.log(`imagesPackaged: ${cameraName}_images_${timestamp}.zip`);
      message.success(t('logManage.imagesPackaged'));
    } catch (error) {
      console.error('downloadCameraImages failed:', error);
      message.error(t('logManage.imagesPackagedFailed'));
    }
  };
  /**
   * 渲染单张图片缩略图
   * 点击缩略图时打开大图预览
   */
  const renderImagePlaceholder = (image, index, cameraTitle, images) => {
    const { data: imagePath, timestamp } = image;
    const imageUrl = buildImageUrl(imagePath);

    const handlePreview = () => {
      // 记录当前相机下所有图片，支持轮播
      const list = (images || [])
        .map((img) => {
          const { data: path, timestamp: ts } = img || {};
          const url = buildImageUrl(path);
          return url
            ? {
              url,
              timestamp: ts,
            }
            : null;
        })
        .filter(Boolean);

      setPreviewImages(list);
      setPreviewIndex(index);
      setPreviewImageUrl(imageUrl);
      setPreviewTitle(cameraTitle || '');
      setPreviewVisible(true);
    };

    return (
      <div
        key={index}
        className={styles.imagePlaceholder}
        onClick={handlePreview}
      >
        <img src={imageUrl} alt={timestamp} />
      </div>
    );
  };

  const renderCameraSection = (camera, index) => {
    const { images = [], camera_info = {} } = camera;
    const { name, home_name, room_name } = camera_info || {};
    const cameraTitle = `${name}(${home_name || ''}${room_name || ''})`;
    return (
      <div key={index} className={styles.cameraSection}>
        <div className={styles.cameraTitleWrapper}>
          <h3 className={styles.cameraTitle}>{cameraTitle}</h3>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={() => downloadCameraImages(camera)}
            size="small"
            disabled={!images || images.length === 0}
          >
            {t('common.download')}
          </Button>
        </div>
        {images?.length > 0
          ? (
            <div className={styles.imageGrid}>
              {images?.map((image, imgIndex) =>
                renderImagePlaceholder(image, imgIndex, cameraTitle, images)
              )}
            </div>
            )
          : <div className={styles.emptyWrap}><Empty description="No data" /></div>}
      </div>
    )
  };

  /**
   * 关闭预览弹窗并重置状态
   */
  const handleClosePreview = () => {
    setPreviewVisible(false);
    setPreviewImages([]);
    setPreviewIndex(0);
    setPreviewImageUrl('');
  };

  /**
   * 切换到上一张图片
   */
  const handlePrev = () => {
    if (!previewImages.length || previewIndex <= 0) return;
    const newIndex = previewIndex - 1;
    setPreviewIndex(newIndex);
    setPreviewImageUrl(previewImages[newIndex].url);
  };

  /**
   * 切换到下一张图片
   */
  const handleNext = () => {
    if (!previewImages.length || previewIndex >= previewImages.length - 1) return;
    const newIndex = previewIndex + 1;
    setPreviewIndex(newIndex);
    setPreviewImageUrl(previewImages[newIndex].url);
  };

  return (
    <>
      <Modal
        title={t('logManage.imageRecord')}
        open={visible}
        onCancel={onCancel}
        footer={null}
        width={800}
        className={styles.imageRecordModal}
        center
      >
        <div className={styles.modalContent}>
          {imageData?.length > 0
            ? imageData?.map((camera, index) => renderCameraSection(camera, index))
            : <div className={styles.emptyWrap}><Empty description="No data" /></div>
          }
        </div>
      </Modal>

      {/* 单张图片预览弹窗，适配移动端和桌面端 */}
      <Modal
        open={previewVisible}
        title={previewTitle || t('logManage.imageRecord')}
        footer={null}
        onCancel={handleClosePreview}
        width="90%"
        style={{ maxWidth: 800 }}
        centered
      >
        {previewImageUrl && (
          <>
            <div style={{ width: '100%', textAlign: 'center' }}>
              <img
                src={previewImageUrl}
                alt={previewTitle}
                style={{
                  maxWidth: '100%',
                  maxHeight: '70vh',
                  objectFit: 'contain',
                  borderRadius: 8,
                }}
              />
            </div>
            {previewImages.length > 1 && (
              <div
                style={{
                  marginTop: 12,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <Button
                  size="small"
                  type="text"
                  icon={<LeftOutlined />}
                  onClick={handlePrev}
                  disabled={previewIndex === 0}
                />
                <span style={{ fontSize: 12, color: '#999' }}>
                  {previewIndex + 1} / {previewImages.length}
                </span>
                <Button
                  size="small"
                  type="text"
                  icon={<RightOutlined />}
                  onClick={handleNext}
                  disabled={previewIndex === previewImages.length - 1}
                />
              </div>
            )}
          </>
        )}
      </Modal>
    </>
  );
};

export default ImageRecordModal;
