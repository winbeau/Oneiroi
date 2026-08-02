import roommateRomanceUrl from "../../../../../assets/images/0001.png";
import snowSwordsmanUrl from "../../../../../assets/images/0002.png";
import qipaoPortraitUrl from "../../../../../assets/images/0003.png";
import fortressCityUrl from "../../../../../assets/images/0004.png";
import heavenRiftUrl from "../../../../../assets/images/0005.png";
import lingyuanSwordUrl from "../../../../../assets/images/0006.png";
import skyCityUrl from "../../../../../assets/images/0007.png";
import midnightDoctorUrl from "../../../../../assets/images/0008.png";

import type { InspirationTemplate } from "./types";

export const DEFAULT_PROMPT =
  "A vast fortified mountain city fills the frame. The camera makes a slow crane-up toward the monumental gate while banners move in the wind, guards cross the lower courtyard, and thin mountain mist drifts between the layered towers. Keep the architecture stable, cinematic, and highly detailed, with restrained natural motion and no dialogue.";

export const inspirationTemplates: InspirationTemplate[] = [
  {
    id: "fortress-city",
    title: "山城要塞苏醒",
    description: "镜头沿城门缓慢抬升，旗帜、薄雾与巡行卫兵让层叠山城逐渐苏醒。",
    category: "历史案例",
    prompt: DEFAULT_PROMPT,
    previewUrl: fortressCityUrl,
    settings: {
      quality: "高质量",
      ratio: "16:9",
      resolution: "1080p",
      duration: 8,
    },
  },
  {
    id: "sky-city",
    title: "云海之上的天空城",
    description: "飞船掠过瀑布与高塔，航拍镜头穿行云层，展现悬崖城市的纵深。",
    category: "历史案例",
    prompt:
      "A majestic sky city rises above a bright sea of clouds. The camera glides forward in a slow aerial establishing shot as ornate airships cross between towers, waterfalls stream from the cliffs, and clouds roll gently through the bridges. Preserve the city's geometry and fine architectural detail with luminous morning light and smooth cinematic motion.",
    previewUrl: skyCityUrl,
    settings: {
      quality: "高质量",
      ratio: "16:9",
      resolution: "1080p",
      duration: 8,
    },
  },
  {
    id: "heaven-rift",
    title: "天幕裂隙",
    description: "孤身剑客面对贯穿云层的金色裂隙，碎石与尘浪围绕光柱翻涌。",
    category: "历史案例",
    prompt:
      "A lone swordsman stands before a colossal golden rift tearing through a storm-black sky. The camera slowly pushes toward the figure while clouds spiral, dust and fragments rise from the ground, and shafts of light pulse through the rift. Keep the warrior's silhouette and ruined landscape stable, emphasizing overwhelming scale and controlled cinematic motion.",
    previewUrl: heavenRiftUrl,
    settings: {
      quality: "高质量",
      ratio: "16:9",
      resolution: "1080p",
      duration: 5,
    },
  },
  {
    id: "qipao-portrait",
    title: "窗边的青瓷旗袍",
    description: "午后侧光掠过青色旗袍与团扇，人物轻抬视线，发丝随微风自然摆动。",
    category: "历史案例",
    prompt:
      "A woman in a pale celadon qipao sits beside a sunlit window holding an embroidered round fan. She slowly lifts her gaze toward the camera as a light breeze moves a few strands of hair and the loose shawl. Warm afternoon highlights travel softly across the silk embroidery; keep her identity, pose, hands, furniture, and room geometry consistent.",
    previewUrl: qipaoPortraitUrl,
    settings: {
      quality: "高质量",
      ratio: "9:16",
      resolution: "1080p",
      duration: 5,
    },
  },
  {
    id: "snow-swordsman",
    title: "雪庭执伞人",
    description: "银发剑客在落雪庭院回眸，伞面轻颤，长发与衣袍被寒风缓缓带起。",
    category: "历史案例",
    prompt:
      "A silver-haired swordsman stands beneath a translucent oil-paper umbrella in a quiet snow-covered courtyard. He turns his eyes toward the camera while snow falls at different depths, the umbrella trembles subtly, and long hair and embroidered robes move in the cold wind. Use a slow portrait push-in and preserve the character's face, costume, and courtyard architecture.",
    previewUrl: snowSwordsmanUrl,
    settings: {
      quality: "高质量",
      ratio: "9:16",
      resolution: "1080p",
      duration: 5,
    },
  },
  {
    id: "lingyuan-sword-design",
    title: "凌渊长剑设定展示",
    description: "以设定板为主体，蓝色能量沿剑身流动，高光依次扫过结构与材质细节。",
    category: "历史案例",
    prompt:
      "A clean technical presentation board showcases the futuristic Chinese longsword Ling Yuan. The orthographic drawings, exploded components, annotations, and overall layout remain fixed while blue energy channels pulse gently along the central blade and precise specular highlights travel across the metal details. Keep every diagram sharp and stable with subtle premium product-animation motion.",
    previewUrl: lingyuanSwordUrl,
    settings: {
      quality: "快速",
      ratio: "16:9",
      resolution: "720p",
      duration: 5,
    },
  },
  {
    id: "roommate-romance-poster",
    title: "合租舍友的暖心片段",
    description: "暖光公寓门口的竖版漫剧构图，行李箱、目光与近距离互动形成温柔的情绪推进。",
    category: "历史案例",
    prompt:
      "Within a polished vertical romance-poster composition, a tall dark-haired roommate gently reaches for the suitcase handle as the woman looks up at him in the warm apartment doorway. Add only subtle blinking, breathing, hair movement, and shifting warm light. Preserve the inset panels, Chinese typography, character identities, hands, clothing, and full poster layout without warping.",
    previewUrl: roommateRomanceUrl,
    settings: {
      quality: "快速",
      ratio: "9:16",
      resolution: "720p",
      duration: 5,
    },
  },
  {
    id: "midnight-doctor-poster",
    title: "深夜敲门的医生",
    description: "雨夜归家后的温柔救治场景，以包扎动作和门内暖光强化竖版漫剧情绪。",
    category: "历史案例",
    prompt:
      "Within a cinematic vertical romance-poster layout, a doctor kneels at the apartment doorway and carefully finishes bandaging the woman's ankle after bringing her home through the rain. The woman steadies herself against the doorframe while warm interior light meets cool blue rain outside. Preserve all inset panels, Chinese typography, faces, hands, medical kit, and poster composition with restrained natural motion.",
    previewUrl: midnightDoctorUrl,
    settings: {
      quality: "快速",
      ratio: "9:16",
      resolution: "720p",
      duration: 5,
    },
  },
];
