import headFrameUrl from "../../../../../assets/head.png";
import tailFrameUrl from "../../../../../assets/tail.png";

import type { InspirationTemplate } from "./types";

export const BOOK_PROMPT =
  "A locked-off wide shot in a bright, elegant bedroom. A woman in white pajamas kneels on the bed facing the built-in headboard shelf. She places both hands on the seamless lower cabinet panel, gently pulls the panel downward on its hinges, and reveals a hidden row of books. Keeping her left hand steady on the open panel, she moves her right hand toward a light-colored hardcover and begins to take the book from the row. She looks down at the book with a calm, focused expression. Her identity, hairstyle, white pajamas, kneeling posture, furniture, bedding, shelf objects, and room geometry remain consistent. The camera stays completely static; warm daylight and shadows remain stable. Only subtle body, hand, hair, fabric, panel, and book movement occurs. Soft cabinet-hinge and book-rustling sounds, no speech.";

export const inspirationTemplates: InspirationTemplate[] = [
  {
    id: "book-transition",
    title: "从隐藏书柜拿起一本书",
    description: "固定机位，人物打开床头隐藏柜门，伸手取出一本浅色精装书。",
    category: "团队灵感",
    prompt: BOOK_PROMPT,
    previewUrl: headFrameUrl,
    secondaryPreviewUrl: tailFrameUrl,
    settings: {
      quality: "高质量",
      ratio: "16:9",
      resolution: "1080p",
      duration: 5,
    },
  },
  {
    id: "product-push-in",
    title: "安静的产品镜头",
    description: "柔和侧光下，镜头缓慢靠近桌面上的产品，背景保持简洁。",
    category: "项目模板",
    prompt:
      "A clean product sits on a quiet wooden table in soft side light. The camera makes a slow, precise push-in while the product remains centered and sharp. Subtle dust motes move through the light, the background stays uncluttered, and the materials remain consistent. No text, no speech.",
    previewUrl: tailFrameUrl,
    settings: {
      quality: "快速",
      ratio: "16:9",
      resolution: "720p",
      duration: 5,
    },
  },
  {
    id: "rainy-character",
    title: "雨后街道的角色镜头",
    description: "人物在雨后的街道轻微转头，地面反射和微风自然变化。",
    category: "历史案例",
    prompt:
      "A person stands on a quiet rain-soaked street at blue hour and slowly turns toward the camera. Wet pavement reflects the soft storefront lights, a light breeze moves the coat, and the background remains stable. The camera makes a restrained lateral move with natural cinematic motion and no dialogue.",
    previewUrl: headFrameUrl,
    settings: {
      quality: "高质量",
      ratio: "16:9",
      resolution: "1080p",
      duration: 8,
    },
  },
];

export { headFrameUrl, tailFrameUrl };
