/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

/******************************
 * purpose: compute the angle of a 8 bit complex number
 *******************************/

#include "costable.h"
#include "defs.h"

unsigned int angle(c16_t perror)
{
  int a;

  // a = atan(perror.i/perror.r);

  //since perror is supposed to be on the unit circle, we can also compute a by
  if (perror.i>=0) {
    if (perror.r>=0)
      a = acostable[min(perror.r,255)];
    else
      a = 32768-acostable[min(-perror.r,255)];

    //a = asin(perror.i);
  } else {
    if (perror.r>=0)
      a = 65536-acostable[min(perror.r,255)];
    else
      a = 32768+acostable[min(-perror.r,255)];

    //a = 2*PI-asin(perror.i);
  }

  return a;

}
