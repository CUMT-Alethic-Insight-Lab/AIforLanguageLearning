<script setup lang="ts">
/**
 * @fileoverview 水球动画组件 (WaterBall)
 * @description 使用 Three.js 实现的 3D 水球动画，用于可视化语音交互状态。
 */

import { onMounted, onUnmounted, ref, watch } from 'vue';
import * as THREE from 'three';

const props = defineProps<{
  isListening: boolean;
  isSpeaking: boolean;
  isProcessing: boolean;
}>();

const containerRef = ref<HTMLElement | null>(null);
let scene: THREE.Scene;
let camera: THREE.PerspectiveCamera;
let renderer: THREE.WebGLRenderer;
let sphere: THREE.Mesh;
let particles: THREE.Points[] = [];
let animationId: number;

// Smooth color transition state
const targetColor = ref(new THREE.Color(0x6366f1));
const currentColor = ref(new THREE.Color(0x6366f1));
const colorLerpSpeed = 0.03;

// Target scale for smooth breathing
const targetScale = ref(1.0);
const currentScale = ref(1.0);
const scaleLerpSpeed = 0.05;

// Watch prop changes to update targets
watch(() => [props.isListening, props.isSpeaking, props.isProcessing], () => {
  if (props.isListening) {
    targetColor.value.setHex(0xff4444);
  } else if (props.isSpeaking) {
    targetColor.value.setHex(0x44ff44);
  } else if (props.isProcessing) {
    targetColor.value.setHex(0xffff44);
  } else {
    targetColor.value.setHex(0x6366f1);
  }
}, { immediate: true });

const initScene = () => {
  if (!containerRef.value) return;

  scene = new THREE.Scene();

  camera = new THREE.PerspectiveCamera(75, containerRef.value.clientWidth / containerRef.value.clientHeight, 0.1, 1000);
  camera.position.z = 250;

  renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "high-performance"
  });
  renderer.setSize(containerRef.value.clientWidth, containerRef.value.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  containerRef.value.appendChild(renderer.domElement);

  createWaterBall();
  createParticleSystem();

  const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
  scene.add(ambientLight);

  const pointLight1 = new THREE.PointLight(0x6366f1, 1.5, 300);
  pointLight1.position.set(100, 100, 100);
  scene.add(pointLight1);

  const pointLight2 = new THREE.PointLight(0x8b5cf6, 1.5, 300);
  pointLight2.position.set(-100, -100, 100);
  scene.add(pointLight2);

  animate();
  window.addEventListener('resize', handleResize);
};

const handleResize = () => {
  if (!containerRef.value || !camera || !renderer) return;
  camera.aspect = containerRef.value.clientWidth / containerRef.value.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(containerRef.value.clientWidth, containerRef.value.clientHeight);
};

const createWaterBall = () => {
  const geometry = new THREE.SphereGeometry(80, 64, 64);
  const material = new THREE.ShaderMaterial({
    uniforms: {
      time: { value: 0 },
      color1: { value: new THREE.Color(0x6366f1) },
      color2: { value: new THREE.Color(0x8b5cf6) },
      color3: { value: new THREE.Color(0x3b82f6) }
    },
    vertexShader: `
      uniform float time;
      varying vec2 vUv;
      varying vec3 vNormal;
      varying vec3 vPosition;

      void main() {
        vUv = uv;
        vNormal = normalize(normalMatrix * normal);

        vec3 pos = position;
        // Gentler waves
        float wave1 = sin(pos.x * 0.04 + time * 0.8) * 2.0;
        float wave2 = cos(pos.y * 0.04 + time * 1.0) * 2.0;
        float wave3 = sin(pos.z * 0.04 + time * 0.6) * 1.5;

        pos += normal * (wave1 + wave2 + wave3);
        vPosition = pos;

        gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
      }
    `,
    fragmentShader: `
      uniform float time;
      uniform vec3 color1;
      uniform vec3 color2;
      uniform vec3 color3;
      varying vec2 vUv;
      varying vec3 vNormal;
      varying vec3 vPosition;

      void main() {
        vec3 viewDirection = normalize(cameraPosition - vPosition);
        float fresnel = pow(1.0 - abs(dot(viewDirection, vNormal)), 3.0);

        float mixValue1 = sin(vPosition.y * 0.008 + time * 0.4) * 0.5 + 0.5;
        float mixValue2 = cos(vPosition.x * 0.008 + time * 0.25) * 0.5 + 0.5;

        vec3 color = mix(color1, color2, mixValue1);
        color = mix(color, color3, mixValue2);
        color = mix(color, vec3(1.0), fresnel * 0.35);

        float gloss = pow(max(dot(vNormal, viewDirection), 0.0), 32.0);
        color += vec3(gloss * 0.4);

        gl_FragColor = vec4(color, 0.88);
      }
    `,
    transparent: true,
    side: THREE.DoubleSide
  });

  sphere = new THREE.Mesh(geometry, material);
  scene.add(sphere);
};

const createParticleSystem = () => {
  const particleCount = 150;
  const geometry = new THREE.BufferGeometry();
  const positions: number[] = [];
  const colors: number[] = [];

  for (let i = 0; i < particleCount; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.random() * Math.PI;
    const radius = 110 + Math.random() * 40;

    const x = radius * Math.sin(phi) * Math.cos(theta);
    const y = radius * Math.sin(phi) * Math.sin(theta);
    const z = radius * Math.cos(phi);

    positions.push(x, y, z);

    const color = new THREE.Color();
    color.setHSL(0.6 + Math.random() * 0.12, 0.75, 0.55);
    colors.push(color.r, color.g, color.b);
  }

  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

  const material = new THREE.PointsMaterial({
    size: 2.5,
    vertexColors: true,
    transparent: true,
    opacity: 0.5,
    blending: THREE.AdditiveBlending
  });

  const particleSystem = new THREE.Points(geometry, material);
  scene.add(particleSystem);
  particles.push(particleSystem);
};

const animate = () => {
  animationId = requestAnimationFrame(animate);
  const time = Date.now() * 0.001;

  // Smooth color lerp
  currentColor.value.lerp(targetColor.value, colorLerpSpeed);

  if (sphere && (sphere.material as THREE.ShaderMaterial).uniforms) {
    (sphere.material as THREE.ShaderMaterial).uniforms.time.value = time;
    (sphere.material as THREE.ShaderMaterial).uniforms.color1.value.copy(currentColor.value);
  }

  // Base rotation - smooth and slow
  if (sphere) {
    sphere.rotation.y += 0.003;
    sphere.rotation.x = Math.sin(time * 0.2) * 0.08;
  }

  // State-based animation targets
  if (props.isListening) {
    // Gentle breathing
    targetScale.value = 1 + Math.sin(time * 2.5) * 0.06;
  } else if (props.isSpeaking) {
    // Soft pulse
    targetScale.value = 1 + Math.sin(time * 4) * 0.04;
  } else if (props.isProcessing) {
    // Slight speed-up in rotation
    if (sphere) sphere.rotation.y += 0.008;
    targetScale.value = 1 + Math.sin(time * 3) * 0.03;
  } else {
    targetScale.value = 1.0;
  }

  // Smooth scale transition
  currentScale.value += (targetScale.value - currentScale.value) * scaleLerpSpeed;
  if (sphere) {
    sphere.scale.set(currentScale.value, currentScale.value, currentScale.value);
  }

  // Gentle particle drift
  particles.forEach((ps, index) => {
    ps.rotation.y += 0.0008 + index * 0.0003;
    ps.rotation.x = Math.sin(time * 0.15 + index) * 0.05;
  });

  if (renderer && scene && camera) {
    renderer.render(scene, camera);
  }
};

onMounted(() => {
  initScene();
});

onUnmounted(() => {
  cancelAnimationFrame(animationId);
  window.removeEventListener('resize', handleResize);
  if (renderer) {
    renderer.dispose();
  }
});
</script>

<template>
  <div ref="containerRef" class="w-full h-full"></div>
</template>
