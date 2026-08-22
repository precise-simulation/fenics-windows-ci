#include <petsc.h>

int main(int argc, char** argv)
{
  PetscErrorCode ierr = PetscInitialize(&argc, &argv, nullptr, nullptr);
  if (ierr)
    return static_cast<int>(ierr);

  return static_cast<int>(PetscFinalize());
}
