/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

#ifndef __MODULATION_COMMON__H__
#define __MODULATION_COMMON__H__
#include "PHY/defs_common.h"
#include "PHY/defs_nr_common.h"
/** @addtogroup _PHY_MODULATION_
 * @{
*/

/*! \brief Extension Type */
typedef enum {
  CYCLIC_PREFIX,
  CYCLIC_SUFFIX,
  ZEROS,
  NONE
} Extension_t;

/**
   \fn void PHY_ofdm_mod(int *input,int *output,int fftsize,unsigned char nb_symbols,unsigned short nb_prefix_samples,Extension_t
   etype) This function performs OFDM modulation with cyclic extension or zero-padding
   @param input The sequence input samples in the frequency-domain  This is a concatenation of the input symbols in SIMD redundant
   format
   @param output The time-domain output signal
   @param fftsize size of OFDM symbol size (\f$N_d\f$)
   @param nb_symbols The number of OFDM symbols in the block
   @param nb_prefix_samples The number of prefix/suffix/zero samples
   @param etype Type of extension (CYCLIC_PREFIX,CYCLIC_SUFFIX,ZEROS)
*/
void PHY_ofdm_mod(const int *input,
                  int *output,
                  int fftsize,
                  unsigned char nb_symbols,
                  unsigned short nb_prefix_samples,
                  Extension_t etype
                 );


void normal_prefix_mod(int32_t *txdataF,int32_t *txdata,uint8_t nsymb,LTE_DL_FRAME_PARMS *frame_parms);
void nr_normal_prefix_mod(c16_t *txdataF,
                          c16_t *txdata,
                          uint8_t nsymb,
                          const NR_DL_FRAME_PARMS *frame_parms,
                          uint32_t slot,
                          bool was_symbol_used[NR_SYMBOLS_PER_SLOT]);

void do_OFDM_mod(c16_t **txdataF, c16_t **txdata, uint32_t frame,uint16_t next_slot, LTE_DL_FRAME_PARMS *frame_parms);


/** @}*/
#endif
