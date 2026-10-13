/*
 * nvinfer custom parser for the YOLO12x LPR+face model (AGENTS.md A.3/A.7).
 *
 * Output tensor "output0": per image [52, 18900] = cx, cy, w, h (network-input pixels) + 48 sigmoid class scores,
 * no NMS in the graph. This parser mirrors lpr_reader.decode (Python, parity-tested):
 *   - one label per anchor = argmax class; kept if score > the class's pre-cluster-threshold from the nvinfer
 *     config ([class-attrs-<id>] = A.7 per-class thresholds);
 *   - class-aware greedy NMS (IoU NMS_IOU), so plates and characters never suppress each other; max MAX_DET boxes;
 *   - the anchor's full 48-score vector is attached to the object as its "instance mask" (48 x 1 floats).
 *     nvinfer copies it to NvDsObjectMeta.mask_params, where the Python probe reads it for constrained decoding.
 *     Use with network-type=3, output-instance-mask=1, cluster-mode=4 and the OSD mask drawing off.
 */
#include <algorithm>
#include <cstring>
#include <vector>

#include "nvdsinfer_custom_impl.h"

static constexpr int kNumClasses = 48;
static constexpr int kNumAttrs = 4 + kNumClasses;
static constexpr float NMS_IOU = 0.5f;
static constexpr size_t MAX_DET = 300;

namespace {

struct Cand {
  float x1, y1, x2, y2, score;
  int cls;
  int anchor;
};

float iou(const Cand &a, const Cand &b) {
  const float ix = std::max(0.f, std::min(a.x2, b.x2) - std::max(a.x1, b.x1));
  const float iy = std::max(0.f, std::min(a.y2, b.y2) - std::max(a.y1, b.y1));
  const float inter = ix * iy;
  const float uni = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter;
  return uni > 0.f ? inter / uni : 0.f;
}

}  // namespace

extern "C" bool NvDsInferParseYolo12Lpr(std::vector<NvDsInferLayerInfo> const &outputLayersInfo,
                                        NvDsInferNetworkInfo const &networkInfo,
                                        NvDsInferParseDetectionParams const &detectionParams,
                                        std::vector<NvDsInferInstanceMaskInfo> &objectList) {
  const NvDsInferLayerInfo *layer = nullptr;
  for (const auto &l : outputLayersInfo)
    if (l.layerName && std::strcmp(l.layerName, "output0") == 0) layer = &l;
  if (!layer && !outputLayersInfo.empty()) layer = &outputLayersInfo[0];
  if (!layer || layer->inferDims.numDims != 2 || static_cast<int>(layer->inferDims.d[0]) != kNumAttrs) {
    fprintf(stderr, "NvDsInferParseYolo12Lpr: expected output [52, N]\n");
    return false;
  }
  const int n = layer->inferDims.d[1];
  const float *out = static_cast<const float *>(layer->buffer);  // channel-major: out[attr * n + anchor]
  const auto &th = detectionParams.perClassPreclusterThreshold;
  const float W = static_cast<float>(networkInfo.width), H = static_cast<float>(networkInfo.height);

  std::vector<Cand> cands;
  for (int a = 0; a < n; ++a) {
    int best = 0;
    float bs = out[4 * n + a];
    for (int c = 1; c < kNumClasses; ++c) {
      const float s = out[(4 + c) * n + a];
      if (s > bs) { bs = s; best = c; }
    }
    const float thr = best < static_cast<int>(th.size()) ? th[best] : 0.25f;
    if (bs <= thr) continue;
    const float cx = out[a], cy = out[n + a], w = out[2 * n + a], h = out[3 * n + a];
    cands.push_back({cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, bs, best, a});
  }
  std::stable_sort(cands.begin(), cands.end(), [](const Cand &x, const Cand &y) { return x.score > y.score; });

  std::vector<Cand> keep;
  for (const auto &c : cands) {
    bool suppressed = false;
    for (const auto &k : keep)
      if (k.cls == c.cls && iou(k, c) > NMS_IOU) { suppressed = true; break; }
    if (!suppressed) {
      keep.push_back(c);
      if (keep.size() >= MAX_DET) break;
    }
  }

  for (const auto &k : keep) {
    NvDsInferInstanceMaskInfo o{};
    o.classId = static_cast<unsigned int>(k.cls);
    o.left = std::max(0.f, k.x1);
    o.top = std::max(0.f, k.y1);
    o.width = std::min(W, k.x2) - o.left;
    o.height = std::min(H, k.y2) - o.top;
    if (o.width <= 0.f || o.height <= 0.f) continue;
    o.detectionConfidence = k.score;
    o.mask = new float[kNumClasses];  // freed by nvinfer
    for (int c = 0; c < kNumClasses; ++c) o.mask[c] = out[(4 + c) * n + k.anchor];
    o.mask_width = kNumClasses;
    o.mask_height = 1;
    o.mask_size = sizeof(float) * kNumClasses;
    objectList.push_back(o);
  }
  return true;
}

CHECK_CUSTOM_INSTANCE_MASK_PARSE_FUNC_PROTOTYPE(NvDsInferParseYolo12Lpr);
