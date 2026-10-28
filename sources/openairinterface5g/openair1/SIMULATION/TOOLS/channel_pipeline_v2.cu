/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

#include "oai_cuda.h"
#include <cstdint>
#include <cstdio>
#include <cuda_runtime.h>
#include "common/platform_types.h"
#include "common/utils/assertions.h"

#define CHECK_CUDA(val)                                                                          \
  {                                                                                              \
    if (val != cudaSuccess) {                                                                    \
      fprintf(stderr, "CUDA Error at %s:%d: %s\n", __FILE__, __LINE__, cudaGetErrorString(val)); \
      exit(EXIT_FAILURE);                                                                        \
    }                                                                                            \
  }

__device__ __forceinline__ cf_t complex_mul(cf_t a, cf_t b)
{
  return cf_t{a.r * b.r - a.i * b.i, a.r * b.i + a.i * b.r};
}

__device__ __forceinline__ cf_t complex_add(cf_t a, cf_t b)
{
  return cf_t{a.r + b.r, a.i + b.i};
}

/**
 * @brief CUDA kernel for performing multipath channel convolution and noise generation
 *
 * This kernel simulates the effect of a multipath channel by convolving the transmitted
 * signal with the channel impulse response. It supports multiple transmit and receive
 * antennas (MIMO). The input signal can be split across two buffers (tx_sig0 and tx_sig1),
 * and the output is similarly written to two buffers (rx_sig0 and rx_sig1).
 *
 * @param channel Pointer to the channel impulse response coefficients for each link.
 * @param tx_sig0 Pointer to the first part of the transmitted signal buffers.
 * @param tx_sig1 Pointer to the second part of the transmitted signal buffers (optional).
 * @param num_samples_tx_sig0 Number of samples in the first transmit buffer NOTE: The total input
     samples provided to the kernel should be equal to num_samples + channel_length - 1. They
     can be arbitrarily split between tx_sig0 and tx_sig1 via this parameter
 * @param rx_sig0 Pointer to the first part of the received signal buffers.
 * @param rx_sig1 Pointer to the second part of the received signal buffers (optional).
 * @param num_samples_rx_sig0 Number of samples in the first receive buffer. NOTE: The total output
     samples privided to the kernel should be equal to num_samples. They can be arbitrarily split
     between rx_sig0 and rx_sig1 via this parameter
 * @param num_samples Total number of output samples to compute.
 * @param channel_length Number of taps in the multipath channel.
 * @param nb_tx Number of transmit antennas.
 * @param nb_rx Number of receive antennas.
 */
__global__ void channel_convolution_and_noise(const cf_t **__restrict__ channel,
                                              const c16_t **__restrict__ tx_sig0,
                                              const c16_t **__restrict__ tx_sig1,
                                              int num_samples_tx_sig0,
                                              c16_t **__restrict__ rx_sig0,
                                              c16_t **__restrict__ rx_sig1,
                                              int num_samples_rx_sig0,
                                              int num_samples,
                                              int channel_length,
                                              int nb_tx,
                                              int nb_rx,
                                              float noise_power,
                                              curandState_t *curand_states)
{
  extern __shared__ cf_t tx_sig[];
  const int i = blockIdx.x * blockDim.x + threadIdx.x;
  const int rx_ant_idx = blockIdx.y;
  const int padding_len = channel_length - 1;

  cf_t rx_tmp = cf_t{0.0f, 0.0f};

  for (int aatx = 0; aatx < nb_tx; aatx++) {
    const int tid = threadIdx.x;
    const int block_start_idx = blockIdx.x * blockDim.x;
    const int shared_mem_size = blockDim.x + padding_len;

    for (int k = tid; k < shared_mem_size; k += blockDim.x) {
      int load_idx = block_start_idx + k;
      if (load_idx < num_samples + padding_len) {
        c16_t val;
        if (load_idx < num_samples_tx_sig0) {
          val = tx_sig0[aatx][load_idx];
        } else {
          val = tx_sig1[aatx][load_idx - num_samples_tx_sig0];
        }
        tx_sig[k] = cf_t{(float)val.r, (float)val.i};
      } else {
        tx_sig[k] = cf_t{0.0f, 0.0f};
      }
    }
    __syncthreads();

    if (i < num_samples) {
      for (int l = 0; l < channel_length; l++) {
        cf_t tx_sample = tx_sig[tid + (channel_length - 1) - l];
        int chan_link_idx = aatx + (rx_ant_idx * nb_tx);
        cf_t chan_weight = channel[chan_link_idx][l];
        rx_tmp = complex_add(rx_tmp, complex_mul(tx_sample, chan_weight));
      }
    }
    __syncthreads();
  }

  if (i < num_samples) {
    if (noise_power > 0.0f) {
      curandState_t local_state = curand_states[rx_ant_idx * num_samples + i];
      float2 awgn = curand_normal2(&local_state);
      if (i < num_samples_rx_sig0) {
        rx_sig0[rx_ant_idx][i].r = rx_tmp.r + awgn.x * noise_power;
        rx_sig0[rx_ant_idx][i].i = rx_tmp.i + awgn.y * noise_power;
      } else {
        rx_sig1[rx_ant_idx][i - num_samples_rx_sig0].r = rx_tmp.r + awgn.x * noise_power;
        rx_sig1[rx_ant_idx][i - num_samples_rx_sig0].i = rx_tmp.i + awgn.y * noise_power;
      }
      curand_states[rx_ant_idx * num_samples + i] = local_state;
    } else {
      if (i < num_samples_rx_sig0) {
        rx_sig0[rx_ant_idx][i].r = rx_tmp.r;
        rx_sig0[rx_ant_idx][i].i = rx_tmp.i;
      } else {
        rx_sig1[rx_ant_idx][i - num_samples_rx_sig0].r = rx_tmp.r;
        rx_sig1[rx_ant_idx][i - num_samples_rx_sig0].i = rx_tmp.i;
      }
    }
  }
}

struct GpuContext {
  cudaStream_t stream;
  curandState_t *curand_states;
  size_t curand_states_size;
};

extern "C" void *cuda_channel_pipeline_init(int max_samples)
{
  GpuContext *ctx = new GpuContext();
  int dev = 0;
  struct cudaDeviceProp prop;
  CHECK_CUDA(cudaGetDeviceProperties(&prop, dev));
  int pageable;
  int integrated;
  cudaDeviceGetAttribute(&pageable, cudaDevAttrPageableMemoryAccess, dev);
  cudaDeviceGetAttribute(&integrated, cudaDevAttrIntegrated,dev);
  if (!(pageable)) {
    return NULL;
  }
  CHECK_CUDA(cudaStreamCreate(&ctx->stream));
  ctx->curand_states = (curandState_t *)create_and_init_curand_states_cuda(max_samples, time(NULL));
  ctx->curand_states_size = max_samples;
  return (void *)ctx;
}

extern "C" void cuda_channel_pipeline_shutdown(void *context_handle)
{
  if (context_handle == nullptr) {
    return;
  }
  GpuContext *ctx = (GpuContext *)context_handle;
  CHECK_CUDA(cudaStreamDestroy(ctx->stream));
  destroy_curand_states_cuda((void *)ctx->curand_states);
  delete ctx;
}

extern "C" void cuda_channel_pipeline(void *context_handle,
                                      const cf_t **channel,
                                      const c16_t **tx_sig0,
                                      const c16_t **tx_sig1,
                                      int num_samples_tx_sig0,
                                      c16_t **rx_sig0,
                                      c16_t **rx_sig1,
                                      int num_samples_rx_sig0,
                                      int num_samples,
                                      int channel_length,
                                      int nb_tx,
                                      int nb_rx,
                                      float noise_power)
{
  AssertFatal(context_handle, "No context handle provided\n");
  AssertFatal(channel, "No channel provided\n");
  AssertFatal(tx_sig0, "No tx_sig0 provided\n");
  AssertFatal(num_samples_tx_sig0 == (num_samples + channel_length - 1) || tx_sig1, "No tx_sig1 provided\n");
  AssertFatal(rx_sig0, "No rx_sig0 provided\n");
  AssertFatal(num_samples_rx_sig0 == num_samples || rx_sig1, "No rx_sig1 provided\n");
  GpuContext *ctx = (GpuContext *)context_handle;
  if (num_samples * nb_rx > ctx->curand_states_size) {
    destroy_curand_states_cuda((void *)ctx->curand_states);
    ctx->curand_states_size = num_samples * nb_rx;
    ctx->curand_states = (curandState_t *)create_and_init_curand_states_cuda(ctx->curand_states_size, time(NULL));
  }
  dim3 threadsPerBlock(512, 1);
  dim3 numBlocks((num_samples + threadsPerBlock.x - 1) / threadsPerBlock.x, nb_rx);
  size_t sharedMemSize = (threadsPerBlock.x + channel_length - 1) * sizeof(cf_t);
  channel_convolution_and_noise<<<numBlocks, threadsPerBlock, sharedMemSize, ctx->stream>>>(channel,
                                                                                            tx_sig0,
                                                                                            tx_sig1,
                                                                                            num_samples_tx_sig0,
                                                                                            rx_sig0,
                                                                                            rx_sig1,
                                                                                            num_samples_rx_sig0,
                                                                                            num_samples,
                                                                                            channel_length,
                                                                                            nb_tx,
                                                                                            nb_rx,
                                                                                            noise_power,
                                                                                            ctx->curand_states);
  CHECK_CUDA(cudaStreamSynchronize(ctx->stream));
}
